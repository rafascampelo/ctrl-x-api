import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_auth import ORIGIN, PASSWORD
from test_care import account, request, sign_in, transition

from app.db.session import get_db
from app.main import app
from app.models.user import Professional
from app.schemas.auth import Registration
from app.services.auth import register


def payload(**changes):
    return {
        'email': 'synthetic-physio@example.test', 'password': PASSWORD,
        'full_name': 'Synthetic Physiotherapist', 'role': 'PROFESSIONAL',
        'crefito_region': 3, 'crefito_number': ' 0012345-f ', **changes,
    }


@pytest.mark.parametrize('changes', [
    {'crefito_region': None}, {'crefito_number': None},
    {'crefito_region': 0}, {'crefito_region': 23}, {'crefito_region': True},
    {'crefito_number': '12345-TO'}, {'crefito_number': '000-F'},
    {'crefito_number': '12345678-F'}, {'crefito_number': '../123-F'},
    {'full_name': ' '}, {'profession': 'physiotherapist'},
    {'verification_status': 'verified'}, {'verified_at': '2026-01-01T00:00:00Z'},
    {'verification_reference': 'forged'}, {'role': 'PATIENT'},
])
def test_registration_rejects_invalid_or_client_verified_crefito(client, changes):
    response = client.post('/api/v1/auth/register', headers=ORIGIN, json=payload(**changes))
    assert response.status_code == 422
    assert response.json() == {'detail': 'Invalid request payload'}


def test_registration_requires_crefito_and_preserves_auth_contract(client):
    data = payload()
    del data['crefito_region'], data['crefito_number']
    assert client.post('/api/v1/auth/register', headers=ORIGIN, json=data).status_code == 422
    created = client.post('/api/v1/auth/register', headers=ORIGIN, json=payload())
    assert created.status_code == 201
    assert set(created.json()) == {'id', 'email', 'role'}
    assert client.post('/api/v1/auth/login', headers=ORIGIN, json={
        'email': payload()['email'], 'password': PASSWORD,
    }).status_code == 200
    profile = client.get('/api/v1/me').json()
    assert profile['crefito_number'] == '12345-F'
    assert profile['verification_status'] == 'unverified'
    assert 'verification_reference' not in profile
    duplicate = client.post('/api/v1/auth/register', headers=ORIGIN, json=payload(
        email='another-synthetic@example.test', crefito_number='12345-F',
    ))
    assert duplicate.status_code == 409
    assert duplicate.json() == {'detail': 'Unable to register with these details'}


def test_unverified_professional_cannot_receive_accept_or_read_patients(client):
    professional = account(client, 'PROFESSIONAL', 'unverified', verified=False)
    assert client.get('/api/v1/patients').status_code == 403
    patient = account(client, 'PATIENT', 'patient')
    assert request(client, professional).status_code == 404
    # Establish a synthetic previously verified relationship, then invalidate verification.
    trusted = account(client, 'PROFESSIONAL', 'trusted')
    sign_in(client, 'patient')
    link = request(client, trusted).json()['id']
    sign_in(client, 'trusted')
    assert transition(client, link, 'accept').status_code == 200
    assert client.patch('/api/v1/me', headers=ORIGIN, json={
        'full_name': 'Changed identity',
    }).json()['verification_status'] == 'unverified'
    assert client.get(f"/api/v1/patients/{patient['id']}").status_code == 403
    assert client.get('/api/v1/patients').status_code == 403
    assert client.get('/api/v1/me/professional-links').status_code == 200
    sign_in(client, 'patient')
    assert transition(client, link, 'revoke').status_code == 204
    # A pending request created before verification withdrawal cannot be accepted.
    with next(app.dependency_overrides[get_db]()) as db:
        row = db.get(Professional, trusted['id'])
        row.verification_status = 'verified'
        row.verified_at = datetime.now(UTC)
        row.verification_reference = 'synthetic-test-review'
        db.commit()
    pending = request(client, trusted).json()['id']
    sign_in(client, 'trusted')
    client.patch('/api/v1/me', headers=ORIGIN, json={'full_name': 'Changed again'})
    assert transition(client, pending, 'accept').status_code == 403
    assert transition(client, pending, 'reject').status_code == 204


def test_profile_registration_ownership_duplicates_and_no_self_verification(client):
    first = account(client, 'PROFESSIONAL', 'first')
    second = account(client, 'PROFESSIONAL', 'second')
    for changes in ({'verification_status': 'verified'}, {'user_id': first['user_id']},
                    {'crefito_number': '123-F'}, {'crefito_region': None, 'crefito_number': None}):
        assert client.patch('/api/v1/me', headers=ORIGIN, json={
            'full_name': second['full_name'], **changes,
        }).status_code == 422
    assert client.patch('/api/v1/me', headers=ORIGIN, json={
        'full_name': 'Conflicting update', 'crefito_region': first['crefito_region'],
        'crefito_number': first['crefito_number'],
    }).status_code == 409
    assert client.get('/api/v1/me').json()['full_name'] == second['full_name']
    updated = client.patch('/api/v1/me', headers=ORIGIN, json={
        'full_name': second['full_name'], 'crefito_region': 4, 'crefito_number': '000123-f',
    })
    assert updated.status_code == 200
    assert updated.json()['crefito_number'] == '123-F'
    assert updated.json()['verification_status'] == 'unverified'
    sign_in(client, 'first')
    assert client.get('/api/v1/me').json() == first
    account(client, 'PATIENT', 'patient')
    assert client.patch('/api/v1/me', headers=ORIGIN, json={
        'full_name': 'Patient', 'crefito_region': 3, 'crefito_number': '123-F',
    }).status_code == 422


def test_mysql_crefito_constraint_and_concurrent_registration(client):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        if os.environ.get('CI') == 'true':
            pytest.fail('TEST_DATABASE_URL is mandatory in CI')
        pytest.skip('requires isolated real MySQL')
    engine = create_engine(url, hide_parameters=True)

    def create(index):
        with Session(engine) as db:
            try:
                register(db, Registration(**payload(email=f'race-{index}@example.test')))
                return 201
            except HTTPException as exc:
                return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(create, range(2))) == [201, 409]
        with Session(engine) as db:
            row = db.scalar(select(Professional))
            row.verification_status = 'verified'
            with pytest.raises(OperationalError, match="ck_professional_verification"):
                db.commit()
            db.rollback()
    finally:
        engine.dispose()
