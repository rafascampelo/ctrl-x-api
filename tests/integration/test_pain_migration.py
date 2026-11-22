import os

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from scripts.ci_database import validate_ci_database


def test_pain_migration_upgrade_drift_and_downgrade():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires disposable MySQL")
    validate_ci_database(url)
    assert os.environ.get("DATABASE_URL") == url
    engine = create_engine(url, hide_parameters=True)
    config = Config("alembic.ini")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM users")) == 0
    try:
        command.downgrade(config, "0006_link_decisions")
        assert "pain_entries" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
        command.check(config)
        inspector = inspect(engine)
        assert "pain_entries" in inspector.get_table_names()
        assert any(constraint['name'] == 'ck_pain_intensity'
                   for constraint in inspector.get_check_constraints("pain_entries"))
        assert any(index['column_names'] == ['patient_id', 'occurred_at', 'id']
                   for index in inspector.get_indexes("pain_entries"))
    finally:
        command.upgrade(config, "head")
        engine.dispose()
