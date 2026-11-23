from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_auth import ORIGIN
from test_care import account, request, sign_in, transition

from app.db.session import get_db
from app.main import app
from app.models.pain_entry import PainEntry
from app.models.professional_link import CareAuditEvent
from app.models.user import User
from app.schemas.pain import PainCreate, PainUpdate
from app.services import pain as service

PAYLOAD = {"region": "Left knee", "intensity": 5, "description": "Synthetic diary text",
           "occurred_at": "2026-01-02T12:30:00-03:00"}


def create(client, **fields):
    response = client.post('/api/v1/me/pain-entries', headers=ORIGIN,
                           json={**PAYLOAD, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def history(client, patient, **params):
    return client.get(f"/api/v1/patients/{patient['id']}/pain-entries", params=params)


def test_patient_diary_persistence_updates_deletion_and_audit(client):
    patient = account(client, 'PATIENT', 'patient')
    entry = create(client)
    assert entry['patient_id'] == patient['id']
    assert entry['occurred_at'] == '2026-01-02T15:30:00Z'
    assert datetime.fromisoformat(entry['created_at']).tzinfo is not None
    with next(app.dependency_overrides[get_db]()) as db:
        stored = db.get(PainEntry, entry['id'])
        assert stored.description == PAYLOAD['description']
    assert history(client, patient).json()['items'] == [entry]
    response = client.patch(f"/api/v1/pain-entries/{entry['id']}", headers=ORIGIN,
                            json={'intensity': 0, 'description': None})
    assert response.status_code == 200
    assert response.json()['intensity'] == 0
    assert response.json()['description'] is None
    assert response.json()['created_at'] == entry['created_at']
    assert response.headers['cache-control'] == 'no-store'
    response = client.delete(f"/api/v1/pain-entries/{entry['id']}", headers=ORIGIN)
    assert response.status_code == 204
    assert not response.content
    assert history(client, patient).json()['items'] == []
    assert client.patch(f"/api/v1/pain-entries/{entry['id']}", headers=ORIGIN,
                        json={'intensity': 2}).status_code == 404
    with next(app.dependency_overrides[get_db]()) as db:
        events = list(db.scalars(select(CareAuditEvent).where(
            CareAuditEvent.action.like('pain_%'),
        )))
        assert {event.action for event in events} == {
            'pain_entry_created', 'pain_entries_viewed',
            'pain_entry_updated', 'pain_entry_deleted',
        }
        assert all(event.actor_id == patient['user_id'] for event in events)
        assert all(event.patient_id == patient['id'] for event in events)
        assert all(PAYLOAD['description'] not in str(event.__dict__) for event in events)


def test_patient_isolation_and_professional_read_only_revocation(client):
    professional = account(client, 'PROFESSIONAL', 'professional')
    other = account(client, 'PROFESSIONAL', 'other')
    patient = account(client, 'PATIENT', 'patient')
    entry = create(client)
    link = request(client, professional).json()['id']
    account(client, 'PATIENT', 'stranger')
    assert history(client, patient).status_code == 404
    for method in ('PATCH', 'DELETE'):
        kwargs = {'json': {'intensity': 1}} if method == 'PATCH' else {}
        assert client.request(method, f"/api/v1/pain-entries/{entry['id']}",
                              headers=ORIGIN, **kwargs).status_code == 404
    sign_in(client, 'professional')
    assert history(client, patient).status_code == 404
    assert transition(client, link, 'accept').status_code == 200
    assert history(client, patient).json()['items'] == [entry]
    assert client.post('/api/v1/me/pain-entries', headers=ORIGIN,
                       json=PAYLOAD).status_code == 403
    assert client.patch(f"/api/v1/pain-entries/{entry['id']}", headers=ORIGIN,
                        json={'intensity': 1}).status_code == 403
    assert client.delete(f"/api/v1/pain-entries/{entry['id']}", headers=ORIGIN).status_code == 403
    sign_in(client, 'other')
    assert other['id'] != professional['id']
    assert history(client, patient).status_code == 404
    sign_in(client, 'professional')
    assert transition(client, link, 'revoke').status_code == 204
    assert history(client, patient).status_code == 404
    sign_in(client, 'patient')
    assert history(client, patient).json()['items'] == [entry]


def test_professional_without_active_link_cannot_read_diary(client):
    account(client, 'PROFESSIONAL', 'unverified', verified=False)
    patient = account(client, 'PATIENT', 'patient')
    create(client)
    sign_in(client, 'unverified')
    assert history(client, patient).status_code == 404


def test_editing_professional_name_preserves_existing_active_link(client):
    professional = account(client, 'PROFESSIONAL', 'professional')
    patient = account(client, 'PATIENT', 'patient')
    create(client)
    link = request(client, professional).json()['id']
    sign_in(client, 'professional')
    assert transition(client, link, 'accept').status_code == 200
    assert history(client, patient).status_code == 200
    assert client.patch('/api/v1/me', headers=ORIGIN,
                        json={'full_name': 'Changed Synthetic Name'}).status_code == 200
    assert history(client, patient).status_code == 200


@pytest.mark.parametrize('fields', [
    {'intensity': -1}, {'intensity': 11}, {'intensity': True}, {'intensity': 1.5},
    {'intensity': '5'}, {'region': ' '}, {'region': 'x' * 101},
    {'description': 'x' * 2001}, {'occurred_at': '2026-01-01T12:00:00'},
    {'occurred_at': None}, {'patient_id': str(uuid4())}, {'id': str(uuid4())},
])
def test_create_validation(client, fields):
    account(client, 'PATIENT', 'patient')
    response = client.post('/api/v1/me/pain-entries', headers=ORIGIN,
                           json={**PAYLOAD, **fields})
    assert response.status_code == 422
    assert response.json() == {'detail': 'Invalid request payload'}


@pytest.mark.parametrize('fields', [
    {}, {'region': None}, {'intensity': None}, {'occurred_at': None},
    {'patient_id': str(uuid4())}, {'intensity': 11}, {'region': ' '},
])
def test_patch_validation(client, fields):
    account(client, 'PATIENT', 'patient')
    entry = create(client)
    assert client.patch(f"/api/v1/pain-entries/{entry['id']}", headers=ORIGIN,
                        json=fields).status_code == 422


def test_pagination_ties_and_date_filter(client):
    patient = account(client, 'PATIENT', 'patient')
    entries = [create(client, intensity=i) for i in (0, 5, 10)]
    create(client, occurred_at='2026-01-03T00:00:00Z')
    params = {'limit': 1, 'start': '2026-01-02T15:30:00Z', 'end': '2026-01-03T00:00:00Z'}
    found = []
    while True:
        response = history(client, patient, **params)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        page = response.json()
        found.extend(item['id'] for item in page['items'])
        if page['next_cursor'] is None:
            break
        params['cursor'] = page['next_cursor']
    assert found == sorted((item['id'] for item in entries), reverse=True)
    assert len(history(client, patient, start='2026-01-02T12:30:00-03:00').json()['items']) == 4
    for query in ({'limit': 0}, {'limit': 101}, {'cursor': 'invalid'},
                  {'start': '2026-01-02'},
                  {'start': '2026-01-03T00:00:00Z', 'end': '2026-01-02T00:00:00Z'},
                  {'cursor': f'2026-01-02T00:00:00|{uuid4()}'}):
        assert history(client, patient, **query).status_code == 422


@pytest.mark.parametrize('method,path,payload', [
    ('POST', '/me/pain-entries', PAYLOAD),
    ('GET', f'/patients/{uuid4()}/pain-entries', None),
    ('PATCH', f'/pain-entries/{uuid4()}', {'intensity': 1}),
    ('DELETE', f'/pain-entries/{uuid4()}', None),
])
def test_authentication_required(client, method, path, payload):
    assert client.request(method, '/api/v1' + path, headers=ORIGIN,
                          json=payload).status_code == 401


def test_origin_and_default_timestamp(client):
    account(client, 'PATIENT', 'patient')
    entry = create(client, occurred_at='2026-01-02T12:30:00.999999Z')
    assert entry['occurred_at'] == '2026-01-02T12:30:00Z'
    response = client.post('/api/v1/me/pain-entries', headers=ORIGIN,
                           json={'region': 'Back', 'intensity': 10})
    assert response.status_code == 201
    assert response.json()['description'] is None
    for method, path, payload in (
        ('POST', '/me/pain-entries', PAYLOAD),
        ('PATCH', f"/pain-entries/{entry['id']}", {'intensity': 1}),
        ('DELETE', f"/pain-entries/{entry['id']}", None),
    ):
        assert client.request(method, '/api/v1' + path, json=payload).status_code == 403
    assert client.options('/api/v1/pain-entries/' + entry['id'], headers={
        **ORIGIN, 'Access-Control-Request-Method': 'DELETE',
        'Access-Control-Request-Headers': 'content-type',
    }).status_code == 200


def test_revoked_session_cannot_read_or_mutate(client):
    patient = account(client, 'PATIENT', 'patient')
    entry = create(client)
    cookies = dict(client.cookies)
    assert client.post('/api/v1/auth/logout', headers=ORIGIN).status_code == 204
    client.cookies.update(cookies)
    assert history(client, patient).status_code == 401
    assert client.post('/api/v1/me/pain-entries', headers=ORIGIN,
                       json=PAYLOAD).status_code == 401
    assert client.patch(f"/api/v1/pain-entries/{entry['id']}", headers=ORIGIN,
                        json={'intensity': 1}).status_code == 401
    assert client.delete(f"/api/v1/pain-entries/{entry['id']}", headers=ORIGIN).status_code == 401


def test_service_enforces_ownership_and_roles_without_http_guards(client):
    from fastapi import HTTPException

    patient = account(client, 'PATIENT', 'patient')
    entry = create(client)
    stranger = account(client, 'PATIENT', 'stranger')
    professional = account(client, 'PROFESSIONAL', 'professional')
    with next(app.dependency_overrides[get_db]()) as db:
        actor = db.get(User, stranger['user_id'])
        with pytest.raises(HTTPException) as error:
            service.change_entry(db, actor, entry['id'], PainUpdate(intensity=1))
        assert error.value.status_code == 404
        with pytest.raises(HTTPException) as error:
            service.list_entries(db, actor, patient['id'], None, None, None, 20)
        assert error.value.status_code == 404
        actor = db.get(User, professional['user_id'])
        with pytest.raises(HTTPException) as error:
            service.create_entry(db, actor, PainCreate(**PAYLOAD))
        assert error.value.status_code == 403
        with pytest.raises(HTTPException) as error:
            service.change_entry(db, actor, entry['id'], None)
        assert error.value.status_code == 403
