import os

import pytest
from sqlalchemy import create_engine, text

from scripts import migrate_production
from scripts.ci_database import validate_ci_database


@pytest.mark.parametrize('failure', [False, True])
def test_mysql_release_holds_lock_on_migration_connection_and_always_releases(
    client, monkeypatch, failure,
):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        if os.environ.get('CI') == 'true':
            pytest.fail('TEST_DATABASE_URL is mandatory in CI')
        pytest.skip('requires isolated MySQL 8.4')
    validate_ci_database(url)
    monkeypatch.setenv('DATABASE_URL', url)
    engine = create_engine(url, hide_parameters=True)
    monkeypatch.setattr(migrate_production, 'production_engine', lambda: engine)
    original_upgrade = migrate_production.command.upgrade

    def upgrade(config, revision):
        connection = config.attributes['connection']
        assert connection.scalar(text('SELECT IS_USED_LOCK(:name)'), {
            'name': migrate_production.LOCK_NAME,
        }) == connection.scalar(text('SELECT CONNECTION_ID()'))
        if failure:
            raise RuntimeError('synthetic migration failure')
        original_upgrade(config, revision)

    monkeypatch.setattr(migrate_production.command, 'upgrade', upgrade)
    assert migrate_production.main() == int(failure)
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT IS_FREE_LOCK(:name)'), {
            'name': migrate_production.LOCK_NAME,
        }) == 1
    engine.dispose()
