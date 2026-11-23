import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.auth import AuthEvent, AuthSession, LoginLimit
from app.models.crefito_review import CrefitoReview
from app.models.pain_entry import PainEntry
from app.models.professional_link import CareAuditEvent, ProfessionalLink
from app.models.user import Patient, Professional, User
from scripts.ci_database import validate_ci_database


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "synthetic-secret-for-tests-only-1234567890")
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://unused:unused@localhost/unused")
    monkeypatch.setenv("APP_ENV", "test")
    get_settings.cache_clear()
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        validate_ci_database(url)
        engine = create_engine(url, hide_parameters=True)
    else:
        if os.environ.get("CI") == "true":
            pytest.fail("TEST_DATABASE_URL is required in CI")
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)

    def db_override():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()
    with Session(engine) as db:
        for model in (CareAuditEvent, PainEntry, ProfessionalLink, AuthEvent, AuthSession, LoginLimit,
                      Patient, CrefitoReview, Professional, User):
            db.execute(delete(model))
        db.commit()
    engine.dispose()
    get_settings.cache_clear()
