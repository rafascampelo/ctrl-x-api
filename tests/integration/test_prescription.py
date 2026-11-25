from uuid import uuid4

from sqlalchemy import select
from test_auth import ORIGIN
from test_care import account, request, sign_in, transition
from test_clinical_record import linked_accounts

from app.db.session import get_db
from app.main import app
from app.models.professional_link import CareAuditEvent

ME = "/api/v1/me/prescriptions"
ROUTINE = {
    "title": "Synthetic routine",
    "frequency": "Twice a week",
    "clinical_notes": "Synthetic instructions",
    "exercises": [
        {"name": "Synthetic exercise A", "sets": 2, "reps": "10 repetitions"},
        {"name": "Synthetic exercise B", "sets": 1, "reps": "30 seconds"},
    ],
}


def patient_path(patient):
    return f"/api/v1/patients/{patient['id']}/prescriptions"


def create(client, patient, payload=ROUTINE):
    response = client.post(patient_path(patient), json=payload, headers=ORIGIN)
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_exercise_completion_appears_in_timeline_and_calendar(client):
    clinician, patient, _ = linked_accounts(client)
    routine = create(client, patient)
    assert routine["professional_id"] == clinician["id"]
    assert routine["professional_name"] == clinician["full_name"]
    assert routine["frequency"] == ROUTINE["frequency"]
    assert routine["completions"] == []
    assert [row["name"] for row in routine["exercises"]] == [item["name"] for item in ROUTINE["exercises"]]
    assert client.get(patient_path(patient)).json()["items"] == [routine]
    completion_path = f"{ME}/{routine['id']}/completions"
    assert client.post(completion_path, json={}, headers=ORIGIN).status_code == 403

    sign_in(client, "patient")
    assert client.get(ME).json()["items"] == [routine]
    response = client.post(completion_path, json={"notes": " Synthetic progress "}, headers=ORIGIN)
    assert response.status_code == 201
    completion = response.json()
    assert completion["notes"] == "Synthetic progress"
    assert completion["completed_at"].endswith("Z")
    assert client.get(ME).json()["items"] == [{**routine, "completions": [completion]}]
    day = completion["completed_at"][:10]
    events = client.get("/api/v1/me/timeline", params={"category": "exercise", "date": day}).json()
    assert [(item["id"], item["category"]) for item in events["items"]] == [(completion["id"], "exercise")]
    assert events["items"][0]["occurred_at"] == completion["completed_at"]
    assert events["items"][0]["summary"] == ROUTINE["title"]
    calendar = client.get("/api/v1/me/calendar", params={"month": day[:7]}).json()
    assert calendar["days"] == [{"date": day, "pain_count": 0, "exercise_count": 1}]

    with next(app.dependency_overrides[get_db]()) as db:
        events = list(db.scalars(
            select(CareAuditEvent).where(
                CareAuditEvent.resource_id.in_([routine["id"], completion["id"]]),
            ),
        ))
        assert {event.action for event in events} == {"prescription_created", "prescription_completion_created"}


def test_prescriptions_respect_ownership_and_revocation(client):
    clinician, patient, link = linked_accounts(client)
    routine = create(client, patient)
    path = patient_path(patient)
    completion_path = f"{ME}/{routine['id']}/completions"
    outsider = account(client, "PATIENT", "outsider")
    assert client.get(ME).json()["items"] == []
    assert client.get(path).status_code == 403
    assert client.post(completion_path, json={}, headers=ORIGIN).status_code == 404
    assert client.post(patient_path(outsider), json=ROUTINE, headers=ORIGIN).status_code == 403

    successor = account(client, "PROFESSIONAL", "successor")
    assert client.get(path).status_code == 404
    assert client.post(path, json=ROUTINE, headers=ORIGIN).status_code == 404

    sign_in(client, "patient")
    assert transition(client, link, "revoke").status_code == 204
    assert client.get(ME).json()["items"][0]["professional_id"] == clinician["id"]
    assert client.post(completion_path, json={}, headers=ORIGIN).status_code == 201
    new_link = request(client, successor).json()["id"]

    sign_in(client, "clinician")
    assert client.get(path).status_code == 404
    assert client.post(path, json=ROUTINE, headers=ORIGIN).status_code == 404
    sign_in(client, "successor")
    assert transition(client, new_link, "accept").status_code == 200
    assert client.get(path).json()["items"][0]["professional_id"] == clinician["id"]


def test_prescription_validation_and_pagination(client):
    _, patient, _ = linked_accounts(client)
    path = patient_path(patient)
    for invalid in (
        {"title": " "}, {"exercises": []}, {"patient_id": str(uuid4())},
        {"exercises": [{**ROUTINE["exercises"][0], "sets": 21}]},
        {"exercises": [{**ROUTINE["exercises"][0], "sets": True}]},
    ):
        assert client.post(path, json={**ROUTINE, **invalid}, headers=ORIGIN).status_code == 422
    ids = {create(client, patient)["id"], create(client, patient)["id"]}
    page = client.get(path, params={"limit": 1}).json()
    remaining = client.get(path, params={"limit": 1, "cursor": page["next_cursor"]}).json()
    assert {page["items"][0]["id"], remaining["items"][0]["id"]} == ids
    assert remaining["next_cursor"] is None
    sign_in(client, "patient")
    assert client.post(f"{ME}/{page['items'][0]['id']}/completions", headers=ORIGIN, json={
        "completed_at": "2026-01-01T00:00:00Z",
    }).status_code == 422
    client.cookies.clear()
    assert client.get(ME).status_code == 401
