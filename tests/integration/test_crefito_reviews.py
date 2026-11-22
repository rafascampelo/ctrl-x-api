from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth import ORIGIN
from test_care import account, request, sign_in, transition

from app.db.session import get_db
from app.main import app
from app.models.crefito_review import CrefitoResult, CrefitoReview
from app.models.user import Professional
from app.services.crefito_reviews import pending_review, record_result


@pytest.fixture
def db():
    yield from app.dependency_overrides[get_db]()


@pytest.mark.parametrize("result", list(CrefitoResult))
def test_registry_result_does_not_verify_identity(client, db, result):
    professional = account(client, "PROFESSIONAL", "review", verified=False)
    review = professional["crefito_review"]
    assert review == {"id": review["id"], "status": "created", "result": None}
    reviewer_id = str(uuid4())
    record_result(db, review["id"], result, reviewer_id)
    profile = client.get("/api/v1/me").json()
    assert profile["crefito_review"] == {**review, "status": "processed", "result": result}
    assert profile["verification_status"] == "unverified"
    assert client.get("/api/v1/patients").status_code == 403
    stored = db.get(CrefitoReview, review["id"])
    assert (stored.source, stored.reason, stored.reviewer_id) == ("crefito-3", result, reviewer_id)
    assert stored.reviewed_at
    patient = account(client, "PATIENT", "patient")
    assert "crefito_review" not in patient
    assert request(client, professional).status_code == 404
    assert len(db.scalars(select(CrefitoReview)).all()) == 1


def test_cancelled_registration_withdraws_access_during_existing_session(client, db):
    patient = account(client, "PATIENT", "patient")
    professional = account(client, "PROFESSIONAL", "review")
    sign_in(client, "patient")
    link = request(client, professional).json()["id"]
    sign_in(client, "review")
    assert transition(client, link, "accept").status_code == 200
    patient_url = f"/api/v1/patients/{patient['id']}"
    assert client.get(patient_url).status_code == 200
    review_id = professional["crefito_review"]["id"]
    record_result(db, review_id, CrefitoResult.CANCELLED, str(uuid4()))
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.get(patient_url).status_code == 403
    assert client.get("/api/v1/me/professional-links").json()["items"][0]["status"] == "active"
    assert db.get(CrefitoReview, review_id).authorization_withdrawn


def test_old_result_rejected_after_edit_and_uncovered_region(client, db):
    professional = account(client, "PROFESSIONAL", "review", verified=False)
    previous = professional["crefito_review"]["id"]
    assert client.patch("/api/v1/me", headers=ORIGIN, json={
        "full_name": professional["full_name"], "crefito_review": {"result": "active"},
    }).status_code == 422
    updated = client.patch("/api/v1/me", headers=ORIGIN, json={
        "full_name": "Edited synthetic identity", "crefito_region": 4, "crefito_number": "456-F",
    }).json()["crefito_review"]
    assert updated["id"] != previous
    assert (updated["status"], updated["result"]) == ("processed", "needs_review")
    with pytest.raises(ValueError, match="unavailable"):
        record_result(db, previous, CrefitoResult.ACTIVE, str(uuid4()))
    db.rollback()
    assert db.get(CrefitoReview, updated["id"]).reason == "region_not_covered"


def test_legacy_profile_without_registration_has_no_review(client, db):
    professional = account(client, "PROFESSIONAL", "legacy", verified=False)
    row = db.get(Professional, professional["id"])
    row.crefito_region = row.crefito_number = None
    db.delete(db.get(CrefitoReview, professional["crefito_review"]["id"]))
    db.commit()
    assert client.get("/api/v1/me").json()["crefito_review"] is None
    assert client.patch("/api/v1/me", headers=ORIGIN, json={
        "full_name": "Edited legacy profile",
    }).json()["crefito_review"] is None


def test_duplicate_resolution_is_serialized(client, db):
    engine = db.get_bind()
    if engine.dialect.name != "mysql":
        pytest.skip("requires MySQL row locks")
    professional = account(client, "PROFESSIONAL", "race", verified=False)
    review_id = professional["crefito_review"]["id"]

    def resolve(result):
        with Session(engine) as session:
            try:
                record_result(session, review_id, result, str(uuid4()))
            except ValueError:
                return False
            return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(resolve, (CrefitoResult.ACTIVE, CrefitoResult.CANCELLED))) == [False, True]
    with pytest.raises(ValueError, match="already processed"):
        pending_review(db, review_id)
