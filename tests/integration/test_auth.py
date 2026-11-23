import os
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import COOKIE_NAME, require_role
from app.db.session import get_db
from app.main import app
from app.models.auth import AuthEvent, AuthSession, LoginLimit
from app.models.user import Role

ORIGIN = {"Origin": "http://localhost:3000"}
PASSWORD = "fake-password-123"


def register(client, role="PATIENT", email=" User@Example.test "):
    registration = ({"crefito_region": 3, "crefito_number": "123456-F"}
                    if role == "PROFESSIONAL" else {})
    return client.post("/api/v1/auth/register", headers=ORIGIN, json={
        "email": email, "password": PASSWORD, "full_name": "Fake Person", "role": role,
        **registration,
    })


@pytest.mark.parametrize("role", ["PATIENT", "PROFESSIONAL"])
def test_register_login_and_me(client, role):
    response = register(client, role)
    assert response.status_code == 201
    assert response.json()["email"] == "user@example.test"
    assert "password_hash" not in response.text
    response = client.post("/api/v1/auth/login", headers=ORIGIN,
                           json={"email": "USER@example.test", "password": PASSWORD})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    assert "Max-Age=900" in response.headers["set-cookie"]
    assert response.headers["x-session-remaining"] == "900"
    assert "samesite=none" in response.headers["set-cookie"].lower()
    session = client.get("/api/v1/auth/me", headers=ORIGIN)
    assert session.json()["role"] == role
    assert 0 < int(session.headers["x-session-remaining"]) <= 900
    assert "X-Session-Remaining" in session.headers["access-control-expose-headers"]
    assert register(client).status_code == 409


def test_development_cookie_uses_lax_without_secure(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    register(client)
    response = login(client)
    cookie = response.headers["set-cookie"].lower()
    assert response.status_code == 200
    assert "samesite=lax" in cookie
    assert "secure" not in cookie


def test_invalid_credentials_and_origin(client):
    assert register(client).status_code == 201
    data = {"email": "user@example.test", "password": "incorrect-password"}
    assert client.post("/api/v1/auth/login", headers=ORIGIN, json=data).status_code == 401
    assert client.post("/api/v1/auth/login", json=data).status_code == 403
    invalid = client.post("/api/v1/auth/register", headers=ORIGIN, json={"password": "short"})
    assert invalid.status_code == 422
    assert "short" not in invalid.text


def test_missing_invalid_and_expired_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set(COOKIE_NAME, "invalid")
    assert client.get("/api/v1/auth/me").status_code == 401
    settings = get_settings()
    now = datetime.now(UTC)
    token = jwt.encode({"sub": "00000000-0000-0000-0000-000000000001", "iat": now,
                        "exp": now - timedelta(seconds=1), "iss": settings.jwt_issuer,
                        "aud": settings.jwt_audience}, settings.secret_key.get_secret_value(),
                       algorithm="HS256")
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_role_dependency_rejects_wrong_role(client):
    assert register(client).status_code == 201
    assert client.post("/api/v1/auth/login", headers=ORIGIN,
                       json={"email": "user@example.test", "password": PASSWORD}).status_code == 200
    router = FastAPI()
    router.dependency_overrides[get_db] = app.dependency_overrides[get_db]
    router.get("/professional", dependencies=[Depends(require_role(Role.PROFESSIONAL))])(
        lambda: {"ok": True}
    )
    with TestClient(router, base_url="https://testserver", cookies=client.cookies) as role_client:
        assert role_client.get("/professional").status_code == 403


def login(client, password=PASSWORD):
    return client.post('/api/v1/auth/login', headers=ORIGIN,
                       json={'email': 'user@example.test', 'password': password})


def test_logout_revokes_unexpired_jwt_and_is_idempotent(client):
    register(client)
    assert login(client).status_code == 200
    token = client.cookies.get(COOKIE_NAME)
    assert client.get('/api/v1/auth/me').status_code == 200
    response = client.post('/api/v1/auth/logout', headers=ORIGIN)
    assert response.status_code == 204
    assert response.content == b''
    assert 'Max-Age=0' in response.headers['set-cookie']
    assert 'HttpOnly' in response.headers['set-cookie']
    assert 'Secure' in response.headers['set-cookie']
    assert 'samesite=none' in response.headers['set-cookie'].lower()
    assert response.headers['cache-control'] == 'no-store'
    assert client.get('/api/v1/auth/me').status_code == 401
    client.cookies.set(COOKIE_NAME, token)
    assert client.get('/api/v1/auth/me').status_code == 401
    assert client.post('/api/v1/auth/logout', headers=ORIGIN).status_code == 204


def test_logout_preserves_other_session(client):
    register(client)
    login(client)
    first = client.cookies.get(COOKIE_NAME)
    login(client)
    second = client.cookies.get(COOKIE_NAME)
    assert first != second
    client.post('/api/v1/auth/logout', headers=ORIGIN)
    client.cookies.set(COOKIE_NAME, first)
    assert client.get('/api/v1/auth/me').status_code == 200


@pytest.mark.parametrize('origin', [None, 'null', 'https://evil.example',
                                   'http://localhost:3000.evil.example'])
def test_csrf_rejects_mutations(client, origin):
    register(client)
    login(client)
    headers = {} if origin is None else {'Origin': origin}
    assert client.post('/api/v1/auth/logout', headers=headers).status_code == 403
    assert client.get('/api/v1/auth/me').status_code == 200
    assert client.post('/api/v1/auth/login', headers=headers,
                       json={'email': 'user@example.test', 'password': PASSWORD}).status_code == 403
    assert client.post('/api/v1/auth/register', headers=headers, json={}).status_code == 403


def test_login_limit_and_recovery(client):
    register(client)
    for _ in range(5):
        assert login(client, 'wrong-password-123').status_code == 401
    response = login(client)
    assert response.status_code == 429
    assert 1 <= int(response.headers['retry-after']) <= 300
    # A new HTTP client shares the same database-backed limit.
    with TestClient(app, base_url='https://testserver') as other:
        assert login(other).status_code == 429
    with next(app.dependency_overrides[get_db]()) as db:
        from sqlalchemy import update
        db.execute(update(LoginLimit).values(window_start=datetime.now(UTC) - timedelta(seconds=301)))
        db.commit()
    assert login(client).status_code == 200


@pytest.mark.parametrize('microsecond', [100000, 900000])
def test_login_limit_second_precision_and_expiry(client, monkeypatch, microsecond):
    from sqlalchemy import select

    from app.repositories import auth as repository

    start = datetime(2026, 1, 1, tzinfo=UTC)

    class Clock(datetime):
        instant = start.replace(microsecond=microsecond)

        @classmethod
        def now(cls, tz=None):
            return cls.instant

    monkeypatch.setattr(repository, 'datetime', Clock)
    for _ in range(5):
        assert login(client, 'wrong-password-123').status_code == 401
    blocked = login(client)
    assert blocked.status_code == 429
    assert blocked.headers['retry-after'] == '300'
    with next(app.dependency_overrides[get_db]()) as db:
        limit = db.scalar(select(LoginLimit))
        assert repository.utc(limit.window_start) == start
        assert limit.attempts == 5
    Clock.instant = start + timedelta(seconds=299, microseconds=900000)
    assert login(client).headers['retry-after'] == '1'
    Clock.instant = start + timedelta(seconds=300, microseconds=microsecond)
    assert login(client).status_code == 401
    with next(app.dependency_overrides[get_db]()) as db:
        limit = db.scalar(select(LoginLimit))
        assert repository.utc(limit.window_start) == start + timedelta(seconds=300)
        assert limit.attempts == 1


def test_retry_after_is_bounded_for_previously_rounded_window(client, monkeypatch):
    from sqlalchemy import select

    from app.repositories import auth as repository

    now = datetime(2026, 1, 1, microsecond=900000, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(repository, 'datetime', Clock)
    for _ in range(5):
        assert login(client).status_code == 401
    with next(app.dependency_overrides[get_db]()) as db:
        limit = db.scalar(select(LoginLimit))
        # Simulate a row saved before the fix and rounded up by MySQL DATETIME(0).
        limit.window_start = now.replace(microsecond=0) + timedelta(seconds=1)
        db.commit()
    response = login(client)
    assert response.status_code == 429
    assert response.headers['retry-after'] == '300'
    with next(app.dependency_overrides[get_db]()) as db:
        limit = db.scalar(select(LoginLimit))
        assert limit.attempts == 5
        assert repository.utc(limit.window_start) == now.replace(microsecond=0) + timedelta(seconds=1)


def test_unknown_account_is_limited_and_accounts_are_independent(client):
    for _ in range(5):
        assert login(client).status_code == 401
    assert login(client).status_code == 429
    register(client, email='other@example.test')
    assert client.post('/api/v1/auth/login', headers=ORIGIN,
                       json={'email': 'other@example.test', 'password': PASSWORD}).status_code == 200


def test_expiration_and_session_binding(client):
    register(client)
    login(client)
    token = client.cookies.get(COOKIE_NAME)
    settings = get_settings()
    claims = jwt.decode(token, settings.secret_key.get_secret_value(), algorithms=['HS256'],
                        audience=settings.jwt_audience, issuer=settings.jwt_issuer)
    assert claims['exp'] - claims['iat'] == 900
    with next(app.dependency_overrides[get_db]()) as db:
        session = db.get(AuthSession, claims['jti'])
        session.expires_at = datetime.now(UTC) + timedelta(seconds=30)
        db.commit()
    remaining = client.get('/api/v1/auth/me')
    assert 0 < int(remaining.headers['x-session-remaining']) <= 30
    claims['exp'] = datetime.now(UTC) - timedelta(seconds=1)
    client.cookies.set(COOKIE_NAME, jwt.encode(claims, settings.secret_key.get_secret_value(),
                                            algorithm='HS256'))
    assert client.get('/api/v1/auth/me').status_code == 401
    client.cookies.set(COOKIE_NAME, token)
    with next(app.dependency_overrides[get_db]()) as db:
        session = db.get(AuthSession, claims['jti'])
        session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert client.get('/api/v1/auth/me').status_code == 401
    assert client.post('/api/v1/auth/logout', headers=ORIGIN).status_code == 204


def test_audit_has_no_credentials_or_tokens(client):
    from sqlalchemy import select
    register(client)
    login(client, 'wrong-password-123')
    login(client)
    token = client.cookies.get(COOKIE_NAME)
    client.get('/api/v1/auth/me')
    client.post('/api/v1/auth/logout', headers=ORIGIN)
    with next(app.dependency_overrides[get_db]()) as db:
        events = db.scalars(select(AuthEvent)).all()
        assert {event.action for event in events} == {
            'register_succeeded', 'login_failed', 'login_succeeded',
            'session_viewed', 'logout_succeeded',
        }
        serialized = str([{column.name: getattr(event, column.name)
                           for column in AuthEvent.__table__.columns} for event in events])
        for secret in (PASSWORD, 'wrong-password-123', token, 'user@example.test', 'Fake Person'):
            assert secret not in serialized


def test_cors_and_openapi(client):
    response = client.options('/api/v1/auth/logout', headers={
        **ORIGIN, 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'content-type',
    })
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == ORIGIN['Origin']
    assert response.headers['access-control-allow-credentials'] == 'true'
    response = client.options('/api/v1/auth/logout', headers={
        'Origin': 'https://evil.example', 'Access-Control-Request-Method': 'POST',
    })
    assert response.status_code == 400
    assert 'access-control-allow-origin' not in response.headers
    schema = client.get('/openapi.json').json()
    assert '204' in schema['paths']['/api/v1/auth/logout']['post']['responses']
    assert '429' in schema['paths']['/api/v1/auth/login']['post']['responses']
    assert schema['components']['securitySchemes']['APIKeyCookie']['in'] == 'cookie'


def test_mysql_concurrent_login_limit(client):
    if not os.environ.get('TEST_DATABASE_URL'):
        if os.environ.get('CI') == 'true':
            pytest.fail('TEST_DATABASE_URL is mandatory in CI')
        pytest.skip('requires real MySQL for row-lock concurrency validation')
    from concurrent.futures import ThreadPoolExecutor

    from app.repositories.auth import reserve_login_attempt

    url = os.environ['TEST_DATABASE_URL']
    engine = create_engine(url, hide_parameters=True)

    def reserve(_):
        with Session(engine) as db:
            return reserve_login_attempt(db, 'concurrent@example.test')

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(reserve, range(12)))
        assert results.count(0) == 5
        assert sum(value > 0 for value in results) == 7
    finally:
        engine.dispose()


def test_signed_token_requires_matching_persisted_session(client):
    register(client)
    login(client)
    settings = get_settings()
    token = client.cookies.get(COOKIE_NAME)
    claims = jwt.decode(token, settings.secret_key.get_secret_value(), algorithms=['HS256'],
                        audience=settings.jwt_audience, issuer=settings.jwt_issuer)
    for field, value in [('sub', '00000000-0000-0000-0000-000000000001'),
                         ('jti', '00000000-0000-0000-0000-000000000002')]:
        altered = {**claims, field: value}
        client.cookies.set(COOKIE_NAME, jwt.encode(altered, settings.secret_key.get_secret_value(),
                                                algorithm='HS256'))
        assert client.get('/api/v1/auth/me').status_code == 401
    del claims['jti']
    client.cookies.set(COOKIE_NAME, jwt.encode(claims, settings.secret_key.get_secret_value(),
                                            algorithm='HS256'))
    assert client.get('/api/v1/auth/me').status_code == 401
