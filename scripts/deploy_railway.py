"""Production-only Railway CLI orchestration. Importing never publishes anything."""

import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
PRODUCTION_PROJECT_ID = "d8bc085c-a818-413e-8233-3fabff1cde1f"
PENDING = {"INITIALIZING", "QUEUED", "WAITING", "BUILDING", "DEPLOYING"}


def validate_base_url(base_url: str):
    parsed = urlsplit(base_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")
            or parsed.port not in (None, 443)):
        raise ValueError("BACKEND_PRODUCTION_URL must be a public HTTPS base URL")


def validate_release_config():
    config = json.loads(Path("railway.json").read_text(encoding="utf-8"))
    if (config.get("build", {}).get("builder") != "DOCKERFILE"
            or config.get("deploy", {}).get("preDeployCommand") != [
                "python -m scripts.db db:migrate"
            ] or config.get("deploy", {}).get("healthcheckPath") != "/health"):
        raise ValueError("Release must include the controlled migration and healthcheck configuration")


def verify_api_target(
    project: str,
    service: str,
    environment: str,
    expected_name: str | None = None,
):
    if project != PRODUCTION_PROJECT_ID:
        raise RuntimeError("Refusing deploy outside the production project ID")
    expected_name = expected_name or os.environ.get("RAILWAY_SERVICE_NAME", "").strip()
    if not expected_name or expected_name.casefold() == "mysql":
        raise RuntimeError("Configure RAILWAY_SERVICE_NAME with the current API service name")
    metadata = json.loads(
        railway(
            "status",
            "--project", project,
            "--environment", environment,
            "--json",
        )
    )

    services = [
        edge["node"]
        for edge in metadata["services"]["edges"]
    ]

    environments = [
        edge["node"]
        for edge in metadata["environments"]["edges"]
    ]

    if metadata["id"] != project:
        raise RuntimeError(
            "Railway project ID does not match RAILWAY_PROJECT_ID"
        )

    if not any(
        item["id"] == service and item["name"] == expected_name
        for item in services
    ):
        raise RuntimeError(
            "Refusing deploy: Railway service ID/name mismatch. "
            "Verify the configured API service name. "
            "Check RAILWAY_SERVICE_ID and the Railway service name."
        )

    if not any(
        item["id"] == environment and item["name"] == "production"
        for item in environments
    ):
        raise RuntimeError(
            "Railway environment ID/name mismatch. "
            "Check RAILWAY_ENVIRONMENT_ID and ensure the "
            "Railway environment is named production."
        )

def safe_cli_diagnostics(output: str | None) -> str:
    """Keep CLI errors useful without printing arbitrary remote payloads."""
    if not output:
        return "(empty)"
    output = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
    for name, value in os.environ.items():
        if value and any(part in name.upper() for part in (
            "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "DATABASE_URL", "MYSQL_URL",
        )):
            output = output.replace(value, "[REDACTED]")
    output = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", output)
    output = re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s]+", "[URL REDACTED]", output)
    lines = []
    for line in output.splitlines():
        # Only retain recognizable CLI diagnostics, never JSON or runtime dumps.
        if not re.search(
            r"(?i)error|unauthorized|forbidden|not found|invalid|failed|unexpected|usage:", line
        ):
            continue
        if re.search(r"(?i)token|secret|password|credential|authorization|cookie|=", line):
            lines.append("[Sensitive diagnostic omitted]")
        else:
            lines.append(line[:500])
    return "\n".join(lines)[:2000] or "[Non-diagnostic output omitted]"


def railway(*args: str) -> str:
    result = subprocess.run(
        ["railway", *args], capture_output=True, text=True, timeout=120, check=False,
        stdin=subprocess.DEVNULL
    )
    if result.returncode:
        raise RuntimeError(
            f"Railway {args[0]} failed (exit {result.returncode})\n"
            f"stdout: {safe_cli_diagnostics(result.stdout)}\n"
            f"stderr: {safe_cli_diagnostics(result.stderr)}"
        )
    return result.stdout


def deployment_id_from_upload(output: str) -> str:
    # CLI 5.74.0 returns this structured result with --detach --json.
    candidate = json.loads(output).get("deploymentId", "")
    if isinstance(candidate, str) and re.fullmatch(UUID, candidate):
        return candidate
    raise RuntimeError("Upload returned no deployment ID; refusing to verify an older deployment")


def wait_for_deployment(
    deployment_id: str, service: str, environment: str,
    project: str = PRODUCTION_PROJECT_ID,
) -> None:
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        deployments = json.loads(
            railway("deployment", "list", "--project", project, "--service", service,
                    "--environment", environment, "--limit", "100", "--json")
        )
        current = next((item for item in deployments if item["id"] == deployment_id), None)
        if current:
            status = current["status"]
            print(f"Deployment {deployment_id}: {status}", flush=True)
            if status == "SUCCESS":
                return
            if status not in PENDING:
                raise RuntimeError(f"Publication failed: deployment status {status}")
        time.sleep(10)
    raise TimeoutError("Railway deployment did not succeed within 15 minutes")


def main() -> None:
    if os.environ.get("GITHUB_EVENT_NAME") != "push" or os.environ.get("GITHUB_REF") != (
        "refs/heads/prod"
    ):
        raise RuntimeError("Publication is restricted to a GitHub push on prod")
    for name in (
        "RAILWAY_TOKEN", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID",
        "RAILWAY_ENVIRONMENT_ID", "RAILWAY_SERVICE_NAME", "BACKEND_PRODUCTION_URL",
    ):
        if not os.environ.get(name):
            raise RuntimeError(f"Missing production configuration: {name}")
    project = os.environ["RAILWAY_PROJECT_ID"]
    service = os.environ["RAILWAY_SERVICE_ID"]
    environment = os.environ["RAILWAY_ENVIRONMENT_ID"]
    for value in (project, service, environment):
        if not re.fullmatch(UUID, value):
            raise ValueError("Railway project, service and environment must be UUIDs")
    base_url = os.environ["BACKEND_PRODUCTION_URL"]
    # Validate configuration before making any remote change.
    validate_base_url(base_url)
    validate_release_config()
    verify_api_target(project, service, environment)
    output = railway(
        "up", "--detach", "--json", "--project", project,
        "--service", service, "--environment", environment
    )
    deployment_id = deployment_id_from_upload(output)
    print(f"Uploaded deployment {deployment_id}", flush=True)
    wait_for_deployment(deployment_id, service, environment, project)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(f"Railway reported SUCCESS for production commit `{os.environ['GITHUB_SHA']}`\n\n")
            stream.write(f"Railway deployment: `{deployment_id}`\n")


if __name__ == "__main__":
    main()
