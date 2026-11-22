import json
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from scripts.deploy_railway import (
    PRODUCTION_PROJECT_ID,
    check_health,
    deployment_id_from_upload,
    main,
    railway,
    validate_base_url,
    validate_release_config,
    verify_api_target,
    wait_for_deployment,
)

DEPLOYMENT = "12345678-1234-1234-1234-123456789abc"


def test_extracts_exact_uploaded_deployment():
    output = json.dumps({"deploymentId": DEPLOYMENT, "logsUrl": "https://railway.com/logs"})
    assert deployment_id_from_upload(output) == DEPLOYMENT


def test_missing_deployment_id_fails_closed():
    with pytest.raises(RuntimeError):
        deployment_id_from_upload('{"logsUrl":"https://railway.com/logs"}')


@pytest.mark.parametrize("status", ["FAILED", "CRASHED", "REMOVED", "CANCELED", "UNKNOWN"])
def test_unsuccessful_publication_fails(status):
    with patch(
        "scripts.deploy_railway.railway",
        return_value=json.dumps([{"id": DEPLOYMENT, "status": status}]),
    ), pytest.raises(RuntimeError, match="Publication failed"):
        wait_for_deployment(DEPLOYMENT, "service", "environment")


def test_does_not_accept_previous_successful_deployment():
    with (
        patch("scripts.deploy_railway.railway", return_value='[{"id":"old","status":"SUCCESS"}]'),
        patch("scripts.deploy_railway.time.monotonic", side_effect=[0, 1, 901]),
        patch("scripts.deploy_railway.time.sleep"),
        pytest.raises(TimeoutError),
    ):
        wait_for_deployment(DEPLOYMENT, "service", "environment")


def test_waits_until_uploaded_deployment_succeeds():
    responses = [
        json.dumps([{"id": DEPLOYMENT, "status": status}])
        for status in ("BUILDING", "DEPLOYING", "SUCCESS")
    ]
    with (
        patch("scripts.deploy_railway.railway", side_effect=responses) as cli,
        patch("scripts.deploy_railway.time.sleep"),
    ):
        wait_for_deployment(DEPLOYMENT, "service", "environment")
        assert cli.call_count == 3


def test_cli_nonzero_is_a_publication_failure():
    with (
        patch("scripts.deploy_railway.subprocess.run", return_value=CompletedProcess([], 1)),
        pytest.raises(RuntimeError, match="exit 1"),
    ):
        railway("up", "--detach")


def test_failing_public_health_is_not_accepted():
    with (
        patch("scripts.deploy_railway.urlopen", side_effect=TimeoutError),
        patch("scripts.deploy_railway.time.sleep"),
        pytest.raises(RuntimeError, match="GET /health failed after retries"),
    ):
        check_health("https://api.example.test")


def test_public_health_retries_transient_network_errors_then_accepts_health():
    from urllib.error import URLError

    response = type("HealthResponse", (), {
        "status": 200,
        "__enter__": lambda self: self,
        "__exit__": lambda self, *args: None,
    })()
    response.read = lambda: b'{"status":"ok"}'
    with (
        patch("scripts.deploy_railway.urlopen",
              side_effect=[URLError("temporary DNS failure"), response]) as request,
        patch("scripts.deploy_railway.time.sleep"),
    ):
        check_health("https://api.example.test")
        assert request.call_count == 2


@pytest.mark.parametrize(
    ("event", "ref"),
    [("pull_request", "refs/heads/prod"), ("push", "refs/heads/develop")],
)
def test_nonproduction_events_cannot_publish(monkeypatch, event, ref):
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_REF", ref)
    with patch("scripts.deploy_railway.railway") as cli:
        with pytest.raises(RuntimeError, match="restricted"):
            main()
        cli.assert_not_called()


@pytest.mark.parametrize('url', ['http://api.example.test', 'https://api.example.test/path',
                               'https://api.example.test/#secret', 'https://user@api.example.test'])
def test_invalid_public_url_is_rejected_before_deploy(url):
    with pytest.raises(ValueError):
        validate_base_url(url)


def test_mysql_service_id_cannot_be_deployed_to():
    metadata = {'id': PRODUCTION_PROJECT_ID, 'services': {'edges': [
        {'node': {'id': 'mysql', 'name': 'ctrl-x-mysql'}},
    ]}, 'environments': {'edges': [{'node': {'id': 'production', 'name': 'production'}}]}}
    with (
        patch('scripts.deploy_railway.railway', return_value=json.dumps(metadata)),
        pytest.raises(RuntimeError, match='Refusing deploy'),
    ):
        verify_api_target(PRODUCTION_PROJECT_ID, 'mysql', 'production', 'renamed-api')


def test_api_service_in_selected_environment_is_accepted():
    metadata = {'id': PRODUCTION_PROJECT_ID, 'services': {'edges': [
        {'node': {'id': 'api', 'name': 'renamed-api'}},
    ]}, 'environments': {'edges': [{'node': {'id': 'environment', 'name': 'production'}}]}}
    with patch('scripts.deploy_railway.railway', return_value=json.dumps(metadata)):
        verify_api_target(PRODUCTION_PROJECT_ID, 'api', 'environment', 'renamed-api')


def test_release_without_migration_hook_is_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'railway.json').write_text(json.dumps({
        'build': {'builder': 'DOCKERFILE'}, 'deploy': {'healthcheckPath': '/health'},
    }), encoding='utf-8')
    with pytest.raises(ValueError, match='controlled migration'):
        validate_release_config()


@pytest.mark.parametrize('field,value', [
    ('project', '11111111-1111-1111-1111-111111111111'),
    ('service', 'wrong-service'), ('environment', 'wrong-environment'),
    ('name', 'MySQL'), ('environment_name', 'staging'),
])
def test_target_mismatches_block_deployment(field, value):
    values = {'project': PRODUCTION_PROJECT_ID, 'service': 'api', 'environment': 'env',
              'name': 'renamed-api', 'environment_name': 'production'}
    values[field] = value
    metadata = {'id': values['project'], 'services': {'edges': [
        {'node': {'id': values['service'], 'name': values['name']}},
    ]}, 'environments': {'edges': [
        {'node': {'id': values['environment'], 'name': values['environment_name']}},
    ]}}
    with (
        patch('scripts.deploy_railway.railway', return_value=json.dumps(metadata)),
        pytest.raises(RuntimeError),
    ):
        verify_api_target(PRODUCTION_PROJECT_ID, 'api', 'env', 'renamed-api')


def test_unofficial_configured_project_fails_before_cli():
    with patch('scripts.deploy_railway.railway') as cli:
        with pytest.raises(RuntimeError, match='project ID'):
            verify_api_target('other-project', 'api', 'env', 'renamed-api')
        cli.assert_not_called()


def configure_release(monkeypatch):
    for name, value in {
        'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': 'refs/heads/prod',
        'RAILWAY_TOKEN': 'fake-project-token', 'RAILWAY_PROJECT_ID': PRODUCTION_PROJECT_ID,
        'RAILWAY_SERVICE_ID': DEPLOYMENT, 'RAILWAY_ENVIRONMENT_ID': DEPLOYMENT,
        'RAILWAY_SERVICE_NAME': 'renamed-api',
        'BACKEND_PRODUCTION_URL': 'https://api.example.test',
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv('GITHUB_STEP_SUMMARY', raising=False)


@pytest.mark.parametrize('failure', [False, True])
def test_release_is_explicit_and_failed_predeploy_blocks_acceptance(monkeypatch, failure):
    configure_release(monkeypatch)
    with (
        patch('scripts.deploy_railway.verify_api_target') as verify,
        patch('scripts.deploy_railway.railway',
              return_value=json.dumps({'deploymentId': DEPLOYMENT})) as cli,
        patch('scripts.deploy_railway.wait_for_deployment',
              side_effect=RuntimeError('pre-deploy failed') if failure else None),
        patch('scripts.deploy_railway.check_health') as health,
    ):
        if failure:
            with pytest.raises(RuntimeError, match='pre-deploy failed'):
                main()
            health.assert_not_called()
        else:
            main()
            health.assert_called_once()
        verify.assert_called_once_with(PRODUCTION_PROJECT_ID, DEPLOYMENT, DEPLOYMENT)
        cli.assert_called_once_with(
            'up', '--detach', '--json', '--project', PRODUCTION_PROJECT_ID,
            '--service', DEPLOYMENT, '--environment', DEPLOYMENT,
        )


def test_cli_diagnostics_redact_credentials_and_disable_stdin(monkeypatch):
    monkeypatch.setenv('RAILWAY_TOKEN', 'fake-project-token')
    result = CompletedProcess([], 1,
                              stdout='error: Unauthorized fake-project-token',
                              stderr='error: failed https://user:password@host/path\n'
                                     'Authorization: Bearer unknown-secret\n'
                                     'error: PASSWORD=unknown-password\n'
                                     '{"patient": "private-content"}')
    with (
        patch('scripts.deploy_railway.subprocess.run', return_value=result) as run,
        pytest.raises(RuntimeError) as error,
    ):
        railway('status', '--json')
    message = str(error.value)
    assert 'Unauthorized' in message
    assert 'stdout:' in message and 'stderr:' in message
    for secret in ('fake-project-token', 'password@', 'unknown-secret',
                   'unknown-password', 'private-content'):
        assert secret not in message
    import subprocess
    assert run.call_args.kwargs['stdin'] == subprocess.DEVNULL
    assert 'env' not in run.call_args.kwargs  # Inherit the Actions secret without argv exposure.


def test_checked_in_release_requires_migrations():
    validate_release_config()


def test_workflow_gates_release_and_passes_project_token():
    from pathlib import Path

    yaml = pytest.importorskip('yaml')
    workflow = yaml.safe_load(Path('.github/workflows/deploy-production.yml').read_text())
    job = workflow['jobs']['production']
    assert job['needs'] == 'validate'
    assert job['environment']['name'] == 'production'
    steps = job['steps']
    deploy = next(step for step in steps if step.get('run') == 'python -m scripts.deploy_railway')
    assert deploy['env']['RAILWAY_TOKEN'] == '${{ secrets.RAILWAY_TOKEN }}'
    assert deploy['env']['RAILWAY_SERVICE_NAME'] == '${{ vars.RAILWAY_SERVICE_NAME }}'
    assert not deploy.get('continue-on-error', False)
    assert not any('railway login' in step.get('run', '') for step in steps)
    assert any('@railway/cli@5.74.0' in step.get('run', '') for step in steps)
