"""Startup checks use fake settings and mocked connections; never migrate."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import Settings
from scripts import start_api


@pytest.fixture
def production(monkeypatch):
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    monkeypatch.delenv('CI', raising=False)
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('RAILWAY_ENVIRONMENT_ID', 'fake-environment')
    monkeypatch.setenv('PORT', '8000')
    monkeypatch.setenv('SECRET_KEY', 'fake-secret-with-at-least-32-characters')
    monkeypatch.setenv('CORS_ORIGINS', 'https://frontend.example.test')
    monkeypatch.setenv('DATABASE_URL',
                       'mysql+pymysql://fake:private-password@mysql.railway.internal:3306/fake')
    with patch('app.core.config.get_settings', side_effect=lambda: Settings(_env_file=None)):
        yield


@pytest.mark.parametrize('variable,value,stage', [
    ('APP_ENV', 'Production', 'environment'), ('APP_ENV', None, 'environment'),
    ('PORT', 'private-invalid-port', 'port'), ('PORT', '65536', 'port'),
    ('SECRET_KEY', None, 'settings'), ('SECRET_KEY', 'private-short-secret', 'settings'),
    ('CORS_ORIGINS', '*', 'cors'), ('CORS_ORIGINS', 'http://frontend.example.test', 'cors'),
    ('CORS_ORIGINS', None, 'cors'),
    ('DATABASE_URL', None, 'settings'), ('DATABASE_URL', 'private-invalid-url', 'settings'),
])
def test_invalid_settings_fail_closed_and_name_variable(
    production, monkeypatch, capsys, variable, value, stage,
):
    if value is None:
        monkeypatch.delenv(variable)
    else:
        monkeypatch.setenv(variable, value)
    with patch('scripts.start_api.check_schema') as schema, patch('os.execvp') as execute:
        assert start_api.main() == 1
    schema.assert_not_called()
    execute.assert_not_called()
    output = capsys.readouterr().err
    events = [json.loads(line) for line in output.splitlines()]
    failure = next(event for event in events if event['status'] == 'failed')
    assert failure['stage'] == stage
    assert variable in failure['variables']
    for secret in ('private-password', 'private-short-secret', 'private-invalid-url',
                   'private-invalid-port', 'fake-secret-with-at-least-32-characters'):
        assert secret not in output


@pytest.mark.parametrize('url,code', [
    ('mysql://fake:private@mysql.railway.internal/fake', 'port'),
    ('mysql://fake:private@public.example.test:3306/fake', 'private_host'),
    ('mysql://fake@mysql.railway.internal:3306/fake', 'password'),
    ('sqlite:///fake.db', 'driver'),
])
def test_production_database_validation_names_requirement(production, monkeypatch, capsys, url, code):
    monkeypatch.setenv('DATABASE_URL', url)
    with patch('scripts.migrate_production.create_engine') as engine, patch('os.execvp') as execute:
        assert start_api.main() == 1
    engine.assert_not_called()
    execute.assert_not_called()
    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    failure = next(event for event in events if event['status'] == 'failed')
    assert failure['stage'] == 'database_engine'
    assert failure['code'] == 'production_database_' + code
    assert 'DATABASE_URL' in failure['variables']


def test_schema_failure_logs_stage_without_exception_contents(production, capsys):
    engine = MagicMock()
    with (
        patch('scripts.migrate_production.production_engine', return_value=engine),
        patch('scripts.migrate_production.check_connection'),
        patch('scripts.migrate_production.verify_revision',
              side_effect=ValueError('mysql://user:private-password@host/db')),
        patch('scripts.migrate_production.command.upgrade') as migrate,
        patch('os.execvp') as execute,
    ):
        assert start_api.main() == 1
    output = capsys.readouterr().err
    assert 'alembic_revision' in output
    assert 'private-password' not in output
    migrate.assert_not_called()
    execute.assert_not_called()
    engine.dispose.assert_called_once()


def test_successful_startup_reports_each_stage(production, capsys):
    engine = MagicMock()
    with (
        patch('scripts.migrate_production.production_engine', return_value=engine),
        patch('scripts.migrate_production.check_connection'),
        patch('scripts.migrate_production.verify_revision'),
        patch('os.execvp') as execute,
    ):
        assert start_api.main() == 0
    execute.assert_called_once()
    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert {event['stage'] for event in events if event['status'] == 'passed'} == {
        'environment', 'port', 'settings', 'cors', 'database_engine',
        'database_connection', 'mysql_version', 'alembic_revision',
    }
