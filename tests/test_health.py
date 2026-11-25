import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from app.db import session
from app.main import app


def test_health():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_database_readiness_executes_query(monkeypatch):
    engine = create_engine("sqlite://")
    try:
        monkeypatch.setattr(session, "get_engine", lambda: engine)
        response = TestClient(app).get("/health/db")
    finally:
        engine.dispose()
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("failure", [
    ValueError("synthetic invalid configuration"),
    OperationalError(None, None, ConnectionError("synthetic connection failure")),
])
def test_failed_database_readiness_is_safe_and_preserves_liveness(monkeypatch, caplog, failure):
    def unavailable_engine():
        raise failure

    monkeypatch.setattr(session, "get_engine", unavailable_engine)
    client = TestClient(app)
    response = client.get("/health/db")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert response.headers["cache-control"] == "no-store"
    assert "synthetic" not in caplog.text
    assert client.get("/health").json() == {"status": "ok"}
