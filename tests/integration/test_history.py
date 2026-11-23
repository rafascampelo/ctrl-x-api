import pytest
from test_auth import ORIGIN
from test_care import account
from test_pain import create

TIMELINE = "/api/v1/me/timeline"
CALENDAR = "/api/v1/me/calendar"


def test_month_summary_and_timeline_project_the_same_local_records(client):
    account(client, "PATIENT", "history")
    create(client, occurred_at="2026-11-01T02:59:59Z", intensity=1)
    first = create(client, occurred_at="2026-11-01T03:00:00Z", intensity=4)
    last = create(client, occurred_at="2026-12-01T02:59:59Z", intensity=0)
    create(client, occurred_at="2026-12-01T03:00:00Z", intensity=9)
    filters = {"month": "2026-11", "timezone": "America/Sao_Paulo"}
    calendar = client.get(CALENDAR, params=filters)
    assert calendar.status_code == 200
    assert calendar.headers["cache-control"] == "no-store"
    assert calendar.json() == {
        **filters, "days": [
            {"date": "2026-11-01", "pain_count": 1}, {"date": "2026-11-30", "pain_count": 1},
        ],
        "pain": {"count": 2, "average_intensity": 2.0, "latest_intensity": 0},
    }
    response = client.get(TIMELINE, params={**filters, "category": "pain", "limit": 1})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    page = response.json()
    assert page["items"] == [{
        "id": last["id"], "category": "pain", "title": "Registro de dor",
        "summary": last["description"], "occurred_at": last["occurred_at"],
        "intensity": 0, "region": last["region"],
    }]
    next_page = client.get(TIMELINE, params={**filters, "cursor": page["next_cursor"]}).json()
    assert [event["id"] for event in next_page["items"]] == [first["id"]]
    assert next_page["next_cursor"] is None
    assert client.get(TIMELINE, params={**filters, "category": "exercise"}).json()["items"] == []

    assert client.delete(f"/api/v1/pain-entries/{last['id']}", headers=ORIGIN).status_code == 204
    assert client.get(CALENDAR, params=filters).json()["pain"]["count"] == 1


def test_local_day_uses_next_midnight_across_dst(client):
    account(client, "PATIENT", "dst")
    create(client, occurred_at="2026-03-08T04:59:59Z")
    first = create(client, occurred_at="2026-03-08T05:00:00Z")
    last = create(client, occurred_at="2026-03-09T03:59:59Z")
    create(client, occurred_at="2026-03-09T04:00:00Z")
    response = client.get(TIMELINE, params={"date": "2026-03-08", "timezone": "America/New_York"})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [last["id"], first["id"]]


def test_history_only_reads_the_session_patient(client):
    params = {"month": "2026-01"}
    for path in (TIMELINE, CALENDAR):
        assert client.get(path, params=params).status_code == 401
    account(client, "PATIENT", "first")
    create(client)
    account(client, "PATIENT", "second")
    assert client.get(TIMELINE, params=params).json() == {"items": [], "next_cursor": None}
    assert client.get(CALENDAR, params=params).json()["pain"] == {
        "count": 0, "average_intensity": None, "latest_intensity": None,
    }
    account(client, "PROFESSIONAL", "professional")
    for path in (TIMELINE, CALENDAR):
        assert client.get(path, params=params).status_code == 403


@pytest.mark.parametrize(("path", "params"), [
    (CALENDAR, {"month": "2026-13"}),
    (CALENDAR, {"month": "2026-11", "timezone": "Not/AZone"}),
    (TIMELINE, {"date": "2026-02-30"}),
    (TIMELINE, {"month": "2026-11", "date": "2026-11-01"}),
    (TIMELINE, {"category": "unknown"}),
    (TIMELINE, {"cursor": "invalid"}),
])
def test_rejects_invalid_history_filters(client, path, params):
    account(client, "PATIENT", "history")
    assert client.get(path, params=params).status_code == 422
