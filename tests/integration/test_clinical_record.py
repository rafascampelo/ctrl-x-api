from uuid import uuid4

from sqlalchemy import select
from test_auth import ORIGIN
from test_care import account, request, sign_in, transition
from test_pain import create as create_pain

from app.db.session import get_db
from app.main import app
from app.models.professional_link import CareAuditEvent

RECORDS = "/api/v1/clinical-records"
TIMELINE = "/api/v1/me/timeline"
FIELDS = {
    "chief_complaint": "Synthetic chief complaint",
    "anamnesis": "Synthetic anamnesis",
    "physical_assessment": "Synthetic assessment",
    "body_region": "Synthetic region",
    "functional_limitations": "Synthetic limitations",
    "therapeutic_goals": "Synthetic goals",
    "care_plan": "Synthetic care plan",
    "pain_intensity": 0,
}


def linked_accounts(client):
    clinician = account(client, "PROFESSIONAL", "clinician")
    patient = account(client, "PATIENT", "patient")
    link = request(client, clinician).json()["id"]
    sign_in(client, "clinician")
    assert transition(client, link, "accept").status_code == 200
    return clinician, patient, link


def create(client, patient):
    result = client.post(RECORDS, json={**FIELDS, "patient_id": patient["id"]}, headers=ORIGIN)
    assert result.status_code == 201
    assert result.headers["cache-control"] == "no-store"
    return result.json()


def test_draft_finalization_amendments_and_timeline(client):
    clinician, patient, _ = linked_accounts(client)
    draft = create(client, patient)
    path = f"{RECORDS}/{draft['id']}"
    assert draft["status"] == "draft"
    assert draft["professional_id"] == clinician["id"]
    assert draft["finalized_at"] is None
    assert client.get(path).json() == draft
    assert client.post(f"{path}/amendments", json={"reason": "Test", "content": "Correction"},
                       headers=ORIGIN).status_code == 409

    sign_in(client, "patient")
    pain = create_pain(client, occurred_at="2026-01-01T00:00:00Z")
    assert client.get(path).status_code == 404
    assert client.get(RECORDS).json()["items"] == []
    assert client.get(TIMELINE, params={"category": "clinical_record"}).json()["items"] == []

    sign_in(client, "clinician")
    revised = client.patch(path, json={"pain_intensity": None, "notes": "Synthetic notes"},
                           headers=ORIGIN)
    assert revised.status_code == 200
    assert revised.json()["pain_intensity"] is None
    assert revised.json()["chief_complaint"] == FIELDS["chief_complaint"]
    finalized = client.post(f"{path}/finalize", headers=ORIGIN).json()
    assert finalized["status"] == "finalized"
    assert finalized["finalized_at"].endswith("Z")
    assert client.patch(path, json={"notes": "Attempted overwrite"}, headers=ORIGIN).status_code == 409
    assert client.post(f"{path}/finalize", headers=ORIGIN).status_code == 409
    assert client.delete(path, headers=ORIGIN).status_code == 405
    amendment = client.post(f"{path}/amendments", json={
        "reason": "Test correction", "content": "Synthetic correction",
    }, headers=ORIGIN)
    assert amendment.status_code == 201
    assert amendment.json()["author_id"] == clinician["id"]

    sign_in(client, "patient")
    record = client.get(path).json()
    assert record == {**finalized, "amendments": [amendment.json()]}
    assert client.get(RECORDS).json()["items"] == [record]
    day = record["finalized_at"][:10]
    events = client.get(TIMELINE, params={"category": "clinical_record", "date": day}).json()
    assert [(event["id"], event["category"]) for event in events["items"]] == [
        (draft["id"], "clinical_record"),
    ]
    assert events["items"][0]["summary"] is None
    calendar = client.get("/api/v1/me/calendar", params={"month": day[:7]}).json()
    calendar_day = next(item for item in calendar["days"] if item["date"] == day)
    assert calendar_day["clinical_record_count"] == 1
    first_page = client.get(TIMELINE, params={"limit": 1}).json()
    second_page = client.get(TIMELINE, params={"cursor": first_page["next_cursor"]}).json()
    assert {first_page["items"][0]["id"], second_page["items"][0]["id"]} == {draft["id"], pain["id"]}

    with next(app.dependency_overrides[get_db]()) as db:
        audit = list(db.scalars(select(CareAuditEvent).where(CareAuditEvent.resource_id == draft["id"])))
        assert {event.action for event in audit} == {
            "clinical_record_created", "clinical_record_viewed", "clinical_record_updated",
            "clinical_record_finalized", "clinical_record_amended",
        }


def test_ownership_and_revocation(client):
    clinician, patient, link = linked_accounts(client)
    draft_path = f"{RECORDS}/{create(client, patient)['id']}"
    finalized_path = f"{RECORDS}/{create(client, patient)['id']}"
    assert client.post(f"{finalized_path}/finalize", headers=ORIGIN).status_code == 200
    other = account(client, "PROFESSIONAL", "other")
    assert client.get(finalized_path).status_code == 404
    assert client.get(RECORDS, params={"patient_id": patient["id"]}).status_code == 404
    assert client.post(RECORDS, headers=ORIGIN, json={**FIELDS, "patient_id": patient["id"]}).status_code == 404

    outsider = account(client, "PATIENT", "outsider")
    assert client.get(finalized_path).status_code == 404
    assert client.get(RECORDS, params={"patient_id": patient["id"]}).status_code == 404
    assert client.post(RECORDS, headers=ORIGIN, json={**FIELDS, "patient_id": outsider["id"]}).status_code == 403

    sign_in(client, "patient")
    assert transition(client, link, "revoke").status_code == 204
    assert client.get(finalized_path).json()["professional_id"] == clinician["id"]
    assert client.post(f"{draft_path}/finalize", headers=ORIGIN).status_code == 403
    successor_link = request(client, other).json()["id"]

    sign_in(client, "clinician")
    assert client.get(finalized_path).status_code == 404
    assert client.patch(draft_path, headers=ORIGIN, json={"notes": "Test"}).status_code == 404
    assert client.post(f"{draft_path}/finalize", headers=ORIGIN).status_code == 404

    sign_in(client, "other")
    assert transition(client, successor_link, "accept").status_code == 200
    assert client.get(draft_path).status_code == 404
    assert client.patch(draft_path, headers=ORIGIN, json={"notes": "Test"}).status_code == 404
    assert client.get(finalized_path).json()["professional_id"] == clinician["id"]
    amendment = client.post(f"{finalized_path}/amendments", headers=ORIGIN, json={
        "reason": "Test correction", "content": "Synthetic correction",
    })
    assert amendment.status_code == 201
    assert amendment.json()["author_id"] == other["id"]


def test_clinical_record_input_validation(client):
    _, patient, _ = linked_accounts(client)
    for invalid in ({"pain_intensity": 11}, {"pain_intensity": -1}, {"pain_intensity": True},
                    {"chief_complaint": " "}, {"professional_id": str(uuid4())}):
        response = client.post(RECORDS, headers=ORIGIN, json={
            **FIELDS, "patient_id": patient["id"], **invalid,
        })
        assert response.status_code == 422
    path = f"{RECORDS}/{create(client, patient)['id']}"
    assert client.patch(path, headers=ORIGIN, json={"chief_complaint": None}).status_code == 422
    assert client.patch(path, headers=ORIGIN, json={"status": "finalized"}).status_code == 422
    client.cookies.clear()
    assert client.get(path).status_code == 401
