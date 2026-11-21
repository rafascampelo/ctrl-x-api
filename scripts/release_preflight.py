"""Validate deployment inputs without contacting Railway or exposing values."""

import os
import re

from scripts.deploy_railway import PRODUCTION_PROJECT_ID, UUID, validate_base_url

REQUIRED = (
    "RAILWAY_TOKEN", "RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_SERVICE_ID", "RAILWAY_SERVICE_NAME", "RAILWAY_MIGRATIONS_SERVICE_ID",
    "BACKEND_PRODUCTION_URL",
)


def validate_config():
    errors = []
    for name in REQUIRED:
        if not os.environ.get(name, "").strip():
            kind = "secrets" if name == "RAILWAY_TOKEN" else "variables"
            errors.append(
                f"{name} unavailable. Configure GitHub > Settings > Environments > "
                f"production > Environment {kind}."
            )
        elif name.endswith("_ID") and not re.fullmatch(UUID, os.environ[name]):
            errors.append(f"{name} must be a UUID copied from Railway.")
    if os.environ.get("RAILWAY_PROJECT_ID") != PRODUCTION_PROJECT_ID:
        errors.append("RAILWAY_PROJECT_ID must identify the official production project.")
    if os.environ.get("RAILWAY_SERVICE_NAME", "").strip().casefold() == "mysql":
        errors.append("RAILWAY_SERVICE_NAME must identify the API, not MySQL.")
    if os.environ.get("RAILWAY_API_TOKEN"):
        errors.append("Use only a project token in RAILWAY_TOKEN for production releases.")
    api = os.environ.get("RAILWAY_SERVICE_ID")
    if api and api != os.environ.get("RAILWAY_MIGRATIONS_SERVICE_ID"):
        errors.append("Migration service must equal API for the single-service pre-deploy flow.")
    if os.environ.get("BACKEND_PRODUCTION_URL", "").strip():
        try:
            validate_base_url(os.environ["BACKEND_PRODUCTION_URL"])
        except ValueError:
            errors.append("BACKEND_PRODUCTION_URL must be a public HTTPS base URL.")
    if errors:
        raise ValueError("\n".join(errors))


def main():
    try:
        validate_config()
    except ValueError as error:
        for message in str(error).splitlines():
            print(f"::error::{message}")
        raise SystemExit(1) from None
    print("Production configuration present and structurally valid; authentication pending.")


if __name__ == "__main__":
    main()
