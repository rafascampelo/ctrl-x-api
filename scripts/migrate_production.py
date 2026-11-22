"""Controlled Railway pre-deploy migration; never runs on import or API startup."""

import os
import sys

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from alembic import command
from app.core.database_config import DatabaseSettings
from app.core.startup_diagnostics import ConfigurationError, startup_step

LOCK_NAME = "ctrlx.alembic.production"


def production_engine():
    if os.environ.get("APP_ENV") != "production" or os.environ.get("CI") == "true":
        raise RuntimeError("Production database access requires the Railway production environment")
    url = make_url(DatabaseSettings().database_url.get_secret_value())
    checks = (
        (url.drivername == "mysql+pymysql", "driver", ["DATABASE_URL", "MYSQL_URL"]),
        (bool(url.host) and url.host.endswith(".railway.internal"), "private_host",
         ["DATABASE_URL", "MYSQL_URL", "DB_HOST", "MYSQLHOST"]),
        (url.port == 3306, "port", ["DATABASE_URL", "MYSQL_URL", "DB_PORT", "MYSQLPORT"]),
        (bool(url.username), "username", ["DATABASE_URL", "MYSQL_URL", "DB_USER", "MYSQLUSER"]),
        (bool(url.password), "password",
         ["DATABASE_URL", "MYSQL_URL", "DB_PASSWORD", "MYSQLPASSWORD"]),
        (bool(url.database), "database", ["DATABASE_URL", "MYSQL_URL", "DB_NAME", "MYSQLDATABASE"]),
    )
    for valid, code, variables in checks:
        if not valid:
            raise ConfigurationError("production_database_" + code, variables)
    return create_engine(url, hide_parameters=True, pool_pre_ping=True,
                         connect_args={"connect_timeout": 10, "read_timeout": 600})


def verify_revision(connection, config):
    heads = tuple(ScriptDirectory.from_config(config).get_heads())
    if len(heads) != 1:
        raise RuntimeError("Exactly one Alembic head is required")
    if MigrationContext.configure(connection).get_current_heads() != heads:
        raise RuntimeError("Database migrations are pending; refusing API activation")


def migration_status(connection, config, require_current=False):
    scripts = ScriptDirectory.from_config(config)
    heads = tuple(scripts.get_heads())
    current = MigrationContext.configure(connection).get_current_heads()
    if len(heads) != 1:
        raise RuntimeError("Exactly one Alembic head is required")
    pending = list(scripts.iterate_revisions(heads, current))
    print(f"Schema revisions: current={','.join(current) or 'base'}; head={heads[0]}; "
          f"pending={len(pending)}", flush=True)
    if require_current:
        verify_revision(connection, config)


def check_connection(connection):
    if not connection.scalar(text("SELECT VERSION()")).startswith("8.4."):
        raise RuntimeError("MySQL 8.4 is required")


def check_schema():
    """Read-only startup guard for every replica; never applies migrations."""
    with startup_step("database_engine"):
        engine = production_engine()
    try:
        with startup_step("database_connection"), engine.connect() as connection:
            with startup_step("mysql_version"):
                check_connection(connection)
            with startup_step("alembic_revision"):
                verify_revision(connection, Config("alembic.ini"))
    finally:
        engine.dispose()


def migrate():
    engine = production_engine()
    try:
        with engine.connect() as connection:
            check_connection(connection)
            acquired = connection.scalar(text("SELECT GET_LOCK(:name, 60)"), {"name": LOCK_NAME})
            if acquired != 1:
                raise RuntimeError("Could not acquire the production migration lock")
            try:
                connection.commit()
                config = Config("alembic.ini")
                if len(ScriptDirectory.from_config(config).get_heads()) != 1:
                    raise RuntimeError("Exactly one Alembic head is required")
                config.attributes["connection"] = connection
                migration_status(connection, config)
                command.upgrade(config, "head")
                verify_revision(connection, config)
                migration_status(connection, config, require_current=True)
                print("Production migrations completed and revision verified", flush=True)
            finally:
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": LOCK_NAME})
                connection.commit()
    finally:
        engine.dispose()


def main():
    try:
        migrate()
    except Exception as error:  # noqa: BLE001 -- CLI boundary must redact secret-bearing errors.
        # Connection exceptions may contain credentials or SQL data: do not print them.
        print(f"Production migration failed ({type(error).__name__}); inspect the release plan",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
