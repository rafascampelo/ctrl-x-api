"""Safe startup diagnostics: fixed codes and variable names, never exception text."""

import json
import sys
from contextlib import contextmanager

from pydantic import ValidationError


class ConfigurationError(ValueError):
    def __init__(self, code, variables, message=None):
        super().__init__(message or code)
        self.code = code
        self.variables = tuple(variables)


def emit(stage, status, error=None):
    event = {"event": "api_startup", "stage": stage, "status": status}
    if error is not None:
        event["error_type"] = type(error).__name__
        event["code"] = "startup_check_failed"
        variables = set()
        if isinstance(error, ConfigurationError):
            event["code"] = error.code
            variables.update(error.variables)
        elif isinstance(error, ValidationError):
            event["code"] = "invalid_settings"
            for item in error.errors(include_input=False, include_url=False):
                # Use schema field names only. Never log msg, input, or ctx.
                from app.core.config import Settings

                field = item["loc"][0] if item["loc"] else None
                if field in Settings.model_fields:
                    variables.add(field.upper())
                cause = item.get("ctx", {}).get("error")
                if isinstance(cause, ConfigurationError):
                    variables.update(cause.variables)
                    event["code"] = cause.code
        event["variables"] = sorted(variables)
    print(json.dumps(event), file=sys.stderr, flush=True)


@contextmanager
def startup_step(stage):
    emit(stage, "started")
    try:
        yield
    except Exception as error:
        emit(stage, "failed", error)
        raise
    emit(stage, "passed")
