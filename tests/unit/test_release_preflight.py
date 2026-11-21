import pytest

from scripts.deploy_railway import PRODUCTION_PROJECT_ID
from scripts.release_preflight import REQUIRED, validate_config


def test_reports_every_missing_setting_without_values(monkeypatch):
    for name in REQUIRED:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError) as error:
        validate_config()
    for name in REQUIRED:
        assert f"{name} unavailable" in str(error.value)
    assert "Environment secrets" in str(error.value)
    assert "Environment variables" in str(error.value)


@pytest.fixture
def configured(monkeypatch):
    for index, name in enumerate(REQUIRED):
        monkeypatch.setenv(name, f"00000000-0000-0000-0000-{index:012d}")
    monkeypatch.setenv("RAILWAY_PROJECT_ID", PRODUCTION_PROJECT_ID)
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "renamed-api")
    monkeypatch.setenv("BACKEND_PRODUCTION_URL", "https://api.example.test")
    monkeypatch.setenv("RAILWAY_MIGRATIONS_SERVICE_ID", "00000000-0000-0000-0000-000000000003")


def test_valid_configuration(configured):
    validate_config()


@pytest.mark.parametrize("name", [name for name in REQUIRED if name.endswith("_ID")])
def test_invalid_identifiers_are_redacted(configured, monkeypatch, name):
    monkeypatch.setenv(name, "sensitive-invalid-value")
    with pytest.raises(ValueError) as error:
        validate_config()
    assert name in str(error.value)
    assert "sensitive-invalid-value" not in str(error.value)


def test_different_service_rejected(configured, monkeypatch):
    monkeypatch.setenv("RAILWAY_MIGRATIONS_SERVICE_ID", "11111111-1111-1111-1111-111111111111")
    with pytest.raises(ValueError, match="equal"):
        validate_config()


def test_invalid_url_redacted(configured, monkeypatch):
    monkeypatch.setenv("BACKEND_PRODUCTION_URL", "https://user:private@api.example.test")
    with pytest.raises(ValueError) as error:
        validate_config()
    assert "private" not in str(error.value)


@pytest.mark.parametrize("name,value", [
    ("RAILWAY_PROJECT_ID", "11111111-1111-1111-1111-111111111111"),
    ("RAILWAY_SERVICE_NAME", "MySQL"),
    ("RAILWAY_API_TOKEN", "fake-account-token"),
])
def test_wrong_production_target_or_token_mode_rejected(configured, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        validate_config()
