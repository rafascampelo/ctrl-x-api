import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from itertools import count
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_auth import ORIGIN, PASSWORD

from app.db.session import get_db
from app.main import app
from app.models.professional_link import CareAuditEvent, LinkStatus, ProfessionalLink
from app.models.user import Professional, User
from app.services.care import request_link, transition_link

REGISTRATIONS = count(200000)


def account(client, role, name, verified=True):
    email = f"{name}@example.test"
    registration = ({'crefito_region': 3, 'crefito_number': f'{next(REGISTRATIONS)}-F'}
                    if role == 'PROFESSIONAL' else {})
    response = client.post('/api/v1/auth/register', headers=ORIGIN, json={
        'email': email, 'password': PASSWORD, 'full_name': f'Fake {name}', 'role': role,
        **registration,
    })
    assert response.status_code == 201
    sign_in(client, name)
    if role == 'PROFESSIONAL' and verified:
        # Synthetic trusted review fixture only. No production path verifies a registration.
        with next(app.dependency_overrides[get_db]()) as db:
            professional = db.scalar(select(Professional).where(
                Professional.user_id == response.json()['id'],
            ))
            professional.verification_status = 'verified'
            professional.verified_at = datetime.now(UTC)
            professional.verification_reference = 'synthetic-test-review-not-an-official-result'
            db.commit()
    return client.get('/api/v1/me').json()


def sign_in(client, name):
    client.cookies.clear()
    assert client.post('/api/v1/auth/login', headers=ORIGIN, json={
        'email': f'{name}@example.test', 'password': PASSWORD,
    }).status_code == 200


def request(client, professional):
    return client.post('/api/v1/me/professional-links', headers=ORIGIN,
                       json={'professional_id': professional['id']})


def transition(client, link, action):
    return client.post(f'/api/v1/me/professional-links/{link}/{action}', headers=ORIGIN)


@pytest.mark.parametrize('method,path,payload', [
    ('GET', '/me', None),
    ('PATCH', '/me', {'full_name': 'Fake Name'}),
    ('GET', '/me/professional-links', None),
    ('POST', '/me/professional-links', {'professional_id': str(uuid4())}),
    ('POST', f'/me/professional-links/{uuid4()}/accept', None),
    ('POST', f'/me/professional-links/{uuid4()}/revoke', None),
    ('POST', f'/me/professional-links/{uuid4()}/reject', None),
    ('GET', f'/patients/{uuid4()}', None),
])
def test_care_requires_authenticated_session(client, method, path, payload):
    response = client.request(method, '/api/v1' + path, headers=ORIGIN, json=payload)
    assert response.status_code == 401


def test_profiles_validate_and_preserve_identity(client):
    assert client.get('/api/v1/me').status_code == 401
    patient = account(client, 'PATIENT', 'patient')
    assert patient['role'] == 'PATIENT'
    assert patient['id'] != patient['user_id']
    response = client.patch('/api/v1/me', headers=ORIGIN, json={'full_name': ' New Name '})
    assert response.status_code == 200
    assert response.json()['full_name'] == 'New Name'
    assert response.headers['cache-control'] == 'no-store'
    for data in ({'full_name': ' '}, {'full_name': 'x', 'role': 'PROFESSIONAL'},
                 {'full_name': 'x', 'user_id': str(uuid4())}):
        assert client.patch('/api/v1/me', headers=ORIGIN, json=data).status_code == 422
    assert client.patch('/api/v1/me', json={'full_name': 'x'}).status_code == 403
    assert client.get(f"/api/v1/patients/{patient['id']}").status_code == 200
    preflight = client.options('/api/v1/me', headers={
        **ORIGIN, 'Access-Control-Request-Method': 'PATCH',
        'Access-Control-Request-Headers': 'content-type',
    })
    assert preflight.status_code == 200


def test_link_consent_roles_isolation_and_revocation(client):
    professional = account(client, 'PROFESSIONAL', 'professional')
    other_professional = account(client, 'PROFESSIONAL', 'other-professional')
    other_patient = account(client, 'PATIENT', 'other-patient')
    patient = account(client, 'PATIENT', 'patient')
    response = request(client, professional)
    assert response.status_code == 201
    link = response.json()
    assert link['status'] == 'pending'
    assert link['created_at'].endswith('Z')
    assert request(client, professional).status_code == 409
    assert transition(client, link['id'], 'accept').status_code == 403
    sign_in(client, 'other-patient')
    assert client.get('/api/v1/me/professional-links').json()['items'] == []
    assert transition(client, link['id'], 'revoke').status_code == 404
    assert client.get(f"/api/v1/patients/{patient['id']}").status_code == 404
    sign_in(client, 'other-professional')
    assert transition(client, link['id'], 'accept').status_code == 404
    sign_in(client, 'professional')
    assert request(client, other_professional).status_code == 403
    assert client.get(f"/api/v1/patients/{patient['id']}").status_code == 404
    accepted = transition(client, link['id'], 'accept')
    assert accepted.status_code == 200
    assert accepted.json()['accepted_at'].endswith('Z')
    assert transition(client, link['id'], 'accept').status_code == 409
    assert client.get(f"/api/v1/patients/{patient['id']}").status_code == 200
    assert client.get(f"/api/v1/patients/{other_patient['id']}").status_code == 404
    sign_in(client, 'patient')
    assert transition(client, link['id'], 'revoke').status_code == 204
    assert transition(client, link['id'], 'revoke').status_code == 204
    assert client.get('/api/v1/me/professional-links').json()['items'][0]['status'] == 'revoked'
    sign_in(client, 'professional')
    assert client.get(f"/api/v1/patients/{patient['id']}").status_code == 404
    assert transition(client, link['id'], 'accept').status_code == 409
    sign_in(client, 'patient')
    replacement = request(client, professional)
    assert replacement.status_code == 201
    assert replacement.json()['id'] != link['id']


def test_one_active_link_and_pagination(client):
    first = account(client, 'PROFESSIONAL', 'first')
    second = account(client, 'PROFESSIONAL', 'second')
    account(client, 'PATIENT', 'patient')
    one = request(client, first).json()['id']
    two = request(client, second).json()['id']
    page = client.get('/api/v1/me/professional-links?limit=1').json()
    assert len(page['items']) == 1
    next_page = client.get('/api/v1/me/professional-links', params={
        'limit': 1, 'cursor': page['next_cursor'],
    }).json()
    assert next_page['next_cursor'] is None
    assert next_page['items'][0]['id'] != page['items'][0]['id']
    assert client.get('/api/v1/me/professional-links?limit=101').status_code == 422
    sign_in(client, 'first')
    assert transition(client, one, 'accept').status_code == 200
    sign_in(client, 'second')
    assert transition(client, two, 'accept').status_code == 409
    sign_in(client, 'first')
    assert transition(client, one, 'revoke').status_code == 204
    sign_in(client, 'second')
    assert transition(client, two, 'accept').status_code == 409
    sign_in(client, 'patient')
    history = client.get('/api/v1/me/professional-links').json()['items']
    assert {link['status'] for link in history} == {'revoked', 'cancelled'}
    assert all(link['closed_at'].endswith('Z') for link in history)
    replacement = request(client, second).json()['id']
    sign_in(client, 'second')
    assert transition(client, replacement, 'accept').status_code == 200


def test_link_validation_and_audit_privacy(client):
    professional = account(client, 'PROFESSIONAL', 'professional')
    patient = account(client, 'PATIENT', 'patient')
    assert request(client, {'id': str(uuid4())}).status_code == 404
    assert client.post('/api/v1/me/professional-links', headers=ORIGIN, json={
        'professional_id': professional['id'], 'patient_id': patient['id'],
    }).status_code == 422
    assert client.post('/api/v1/me/professional-links', json={
        'professional_id': professional['id'],
    }).status_code == 403
    link = request(client, professional).json()['id']
    sign_in(client, 'professional')
    transition(client, link, 'accept')
    client.get(f"/api/v1/patients/{patient['id']}")
    transition(client, link, 'revoke')
    with next(app.dependency_overrides[get_db]()) as db:
        events = db.scalars(select(CareAuditEvent)).all()
        actions = {e.action for e in events}
        assert {'profile_viewed', 'link_requested', 'link_accepted', 'patient_viewed',
                'link_revoked'} <= actions
        serialized = str([{c.name: getattr(e, c.name) for c in CareAuditEvent.__table__.columns}
                          for e in events])
        assert PASSWORD not in serialized
        assert '@example.test' not in serialized
        assert 'Fake patient' not in serialized


def test_mysql_concurrent_accept_and_database_constraint(client):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        if os.environ.get('CI') == 'true':
            pytest.fail('TEST_DATABASE_URL is mandatory in CI')
        pytest.skip('requires real MySQL row locks and generated unique column')
    first = account(client, 'PROFESSIONAL', 'first')
    second = account(client, 'PROFESSIONAL', 'second')
    patient = account(client, 'PATIENT', 'patient')
    one = request(client, first).json()['id']
    two = request(client, second).json()['id']
    engine = create_engine(url, hide_parameters=True)

    def accept(pair):
        with Session(engine, expire_on_commit=False) as db:
            try:
                transition_link(db, db.get(User, pair[1]), pair[0], accept=True)
                return 200
            except HTTPException as exc:
                return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(accept, [(one, first['user_id']), (two, second['user_id'])]))
        assert sorted(results) == [200, 409]
        with Session(engine) as db:
            db.add(ProfessionalLink(patient_id=patient['id'], professional_id=first['id'],
                                    status=LinkStatus.ACTIVE))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
    finally:
        engine.dispose()


def test_mysql_concurrent_duplicate_requests(client):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        if os.environ.get('CI') == 'true':
            pytest.fail('TEST_DATABASE_URL is mandatory in CI')
        pytest.skip('requires real MySQL row locks')
    professional = account(client, 'PROFESSIONAL', 'professional')
    patient = account(client, 'PATIENT', 'patient')
    engine = create_engine(url, hide_parameters=True)

    def create(_):
        with Session(engine, expire_on_commit=False) as db:
            try:
                request_link(db, db.get(User, patient['user_id']), professional['id'])
                return 201
            except HTTPException as exc:
                return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(create, range(2))) == [201, 409]
    finally:
        engine.dispose()


def test_linked_patient_list_is_scoped_paginated_and_revoked(client):
    assert client.get('/api/v1/patients').status_code == 401
    professional = account(client, 'PROFESSIONAL', 'list-professional')
    account(client, 'PROFESSIONAL', 'list-outsider')
    first = account(client, 'PATIENT', 'list-first')
    one = request(client, professional).json()['id']
    second = account(client, 'PATIENT', 'list-second')
    two = request(client, professional).json()['id']
    account(client, 'PATIENT', 'list-pending')
    request(client, professional)
    assert client.get('/api/v1/patients').status_code == 403
    sign_in(client, 'list-professional')
    assert client.get('/api/v1/patients').json()['items'] == []
    assert transition(client, one, 'accept').status_code == 200
    assert transition(client, two, 'accept').status_code == 200
    page = client.get('/api/v1/patients?limit=1')
    assert page.status_code == 200
    assert page.headers['cache-control'] == 'no-store'
    following = client.get('/api/v1/patients', params={
        'limit': 1, 'cursor': page.json()['next_cursor'],
    }).json()
    assert following['next_cursor'] is None
    rows = page.json()['items'] + following['items']
    assert {row['id'] for row in rows} == {first['id'], second['id']}
    assert all(set(row) == {'id', 'user_id', 'role', 'full_name'} for row in rows)
    assert client.get('/api/v1/patients?limit=101').status_code == 422
    sign_in(client, 'list-outsider')
    assert client.get('/api/v1/patients').json()['items'] == []
    sign_in(client, 'list-first')
    assert transition(client, one, 'revoke').status_code == 204
    sign_in(client, 'list-professional')
    assert [p['id'] for p in client.get('/api/v1/patients').json()['items']] == [second['id']]


def test_refusal_cancellation_and_patient_controlled_switch(client):
    first = account(client, 'PROFESSIONAL', 'first')
    second = account(client, 'PROFESSIONAL', 'second')
    patient = account(client, 'PATIENT', 'patient')
    cancelled = request(client, first).json()['id']
    assert transition(client, cancelled, 'reject').status_code == 403
    assert transition(client, cancelled, 'revoke').status_code == 204
    refused = request(client, first).json()['id']
    sign_in(client, 'second')
    assert transition(client, refused, 'reject').status_code == 404
    sign_in(client, 'first')
    assert transition(client, cancelled, 'accept').status_code == 409
    assert transition(client, refused, 'reject').status_code == 204
    assert transition(client, refused, 'accept').status_code == 409
    sign_in(client, 'patient')
    current = request(client, first).json()['id']
    stale = request(client, second).json()['id']
    sign_in(client, 'first')
    assert transition(client, current, 'accept').status_code == 200
    assert transition(client, current, 'reject').status_code == 409
    sign_in(client, 'patient')
    assert request(client, second).status_code == 409
    assert transition(client, current, 'revoke').status_code == 204
    replacement = request(client, second).json()['id']
    sign_in(client, 'first')
    assert client.get(f"/api/v1/patients/{patient['id']}").status_code == 404
    sign_in(client, 'second')
    assert transition(client, stale, 'accept').status_code == 409
    assert transition(client, replacement, 'accept').status_code == 200
    sign_in(client, 'patient')
    history = client.get('/api/v1/me/professional-links').json()['items']
    assert len(history) == 5
    assert {link['status'] for link in history} == {'cancelled', 'rejected', 'revoked', 'active'}
    with next(app.dependency_overrides[get_db]()) as db:
        actions = set(db.scalars(select(CareAuditEvent.action)))
        assert {'link_rejected', 'link_cancelled', 'link_superseded', 'link_revoked'} <= actions
