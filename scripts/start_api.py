"""Validate production prerequisites, then replace PID 1 with Uvicorn."""

import os
import sys

from scripts.migrate_production import check_schema


def main():
    from app.core.startup_diagnostics import ConfigurationError, startup_step

    try:
        with startup_step("environment"):
            environment = os.environ.get("APP_ENV", "development")
            if environment not in {"development", "test", "production"}:
                raise ConfigurationError("invalid_app_environment", ["APP_ENV"])
            if os.environ.get("RAILWAY_ENVIRONMENT_ID") and environment != "production":
                raise ConfigurationError("railway_requires_production", ["APP_ENV"])
        with startup_step("port"):
            try:
                port = int(os.environ.get("PORT", "8000"))
                if not 1 <= port <= 65535:
                    raise ValueError
            except ValueError:
                raise ConfigurationError("invalid_port", ["PORT"]) from None
        if environment == "production":
            from app.core.config import get_settings

            with startup_step("settings"):
                settings = get_settings()
            with startup_step("cors"):
                try:
                    if any(not origin.startswith("https://") for origin in settings.origins):
                        raise ValueError
                except ValueError:
                    raise ConfigurationError("invalid_production_cors", ["CORS_ORIGINS"]) from None
            check_schema()
    except Exception:  # noqa: BLE001 -- Each stage emits only safe diagnostic fields.
        return 1
    os.execvp(sys.executable, [sys.executable, "-m", "uvicorn", "app.main:app",
                             "--host", "0.0.0.0", "--port", str(port), "--no-access-log"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
