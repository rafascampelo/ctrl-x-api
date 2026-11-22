import os
from datetime import datetime
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from alembic import command
from scripts.ci_database import validate_ci_database


def test_mysql_is_isolated_and_at_migration_head():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        if os.environ.get("CI") == "true":
            pytest.fail("TEST_DATABASE_URL is mandatory in CI")
        pytest.skip("requires the disposable MySQL service; see CI-CD.md")
    validate_ci_database(url)
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT DATABASE()")) == "ctrlx_ci"
            assert connection.scalar(text("SELECT VERSION()")).startswith("8.4.")
            heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
            assert len(heads) == 1
            assert MigrationContext.configure(connection).get_current_heads() == tuple(heads)
    finally:
        engine.dispose()


def test_mysql_cx02_migration_preserves_legacy_profiles_and_revoked_links():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        if os.environ.get("CI") == "true":
            pytest.fail("TEST_DATABASE_URL is mandatory in CI")
        pytest.skip("requires disposable MySQL")
    validate_ci_database(url)
    assert os.environ.get("DATABASE_URL") == url, "Migrations must target the disposable test database"
    engine = create_engine(url, hide_parameters=True)
    config = Config("alembic.ini")
    ids = {key: str(uuid4()) for key in ("patient_user", "professional_user", "patient", "professional",
                                       "link")}
    # Downgrades are permitted only on the guarded, empty disposable test schema.
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM users")) == 0
    try:
        command.downgrade(config, "0004_professional_links")
        with engine.begin() as connection:
            for key, role in (("patient_user", "PATIENT"), ("professional_user", "PROFESSIONAL")):
                connection.execute(text(
                    "INSERT INTO users (id,email,password_hash,role) VALUES (:id,:email,:hash,:role)"
                ), {"id": ids[key], "email": f"{key}@example.test",
                    "hash": "synthetic-unused-hash", "role": role})
            for table, key, user in (("patients", "patient", "patient_user"),
                                     ("professionals", "professional", "professional_user")):
                connection.execute(text(
                    f"INSERT INTO {table} (id,user_id,full_name) VALUES (:id,:user,:name)"
                ), {"id": ids[key], "user": ids[user], "name": "Synthetic Legacy Profile"})
            connection.execute(text(
                "INSERT INTO professional_links "
                "(id,patient_id,professional_id,status,created_at,accepted_at,revoked_at) "
                "VALUES (:link,:patient,:professional,'revoked',:time,:time,:time)"
            ), {**ids, "time": datetime(2026, 1, 1)})
        command.upgrade(config, "head")
        command.check(config)
        with engine.connect() as connection:
            profile = connection.execute(text(
                "SELECT full_name,crefito_region,crefito_number,verification_status "
                "FROM professionals WHERE id=:professional"
            ), ids).one()
            assert tuple(profile) == ("Synthetic Legacy Profile", None, None, "unverified")
            link = connection.execute(text(
                "SELECT status,revoked_at,closed_at FROM professional_links WHERE id=:link"
            ), ids).one()
            assert link.status == "revoked"
            assert link.closed_at == link.revoked_at == datetime(2026, 1, 1)
    finally:
        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM professional_links WHERE id=:link"), ids)
            connection.execute(text("DELETE FROM patients WHERE id=:patient"), ids)
            connection.execute(text("DELETE FROM professionals WHERE id=:professional"), ids)
            connection.execute(text("DELETE FROM users WHERE id IN (:patient_user,:professional_user)"),
                               ids)
        engine.dispose()
