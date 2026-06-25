import pytest
from pydantic import ValidationError

from app.core.config import APP_NAME, APP_VERSION, Settings

REQUIRED_SETTINGS = {
    "WARDN_HUB_ENVIRONMENT": "local",
    "WARDN_HUB_API_PREFIX": "/api/v1",
    "WARDN_HUB_LOG_LEVEL": "INFO",
    "WARDN_HUB_API_TOKEN_SECRET": "test-token-secret",
    "WARDN_HUB_API_TOKEN_PREFIX": "wardn_hub",
    "WARDN_HUB_SESSION_COOKIE_NAME": "wardn_hub_session",
    "WARDN_HUB_SESSION_SECRET": "test-session-secret",
    "WARDN_HUB_SESSION_TTL_SECONDS": "43200",
    "WARDN_HUB_REGISTRY_PUBLIC_BASE_URL": "http://localhost:3000",
    "WARDN_HUB_DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/wardn_hub",
}


def set_required_settings(monkeypatch, overrides: dict[str, str] | None = None) -> None:
    for key, value in {**REQUIRED_SETTINGS, **(overrides or {})}.items():
        monkeypatch.setenv(key, value)


def test_app_metadata_is_hard_coded(monkeypatch) -> None:
    set_required_settings(monkeypatch)
    monkeypatch.setenv("WARDN_HUB_APP_NAME", "Custom Hub")
    monkeypatch.setenv("WARDN_HUB_APP_VERSION", "9.9.9")

    settings = Settings(_env_file=None)

    assert settings.app_name == APP_NAME
    assert settings.app_version == APP_VERSION


def test_cors_origins_parse_comma_separated_env(monkeypatch) -> None:
    set_required_settings(monkeypatch)
    monkeypatch.setenv("WARDN_HUB_CORS_ORIGINS", "http://localhost:3000, http://localhost:3001")

    settings = Settings(_env_file=None)

    assert settings.cors_origins == ["http://localhost:3000", "http://localhost:3001"]


def test_cors_origins_default_empty_without_env(monkeypatch) -> None:
    set_required_settings(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.cors_origins == []


def test_database_url_is_required_without_env(monkeypatch) -> None:
    required_without_database = {
        key: value for key, value in REQUIRED_SETTINGS.items() if key != "WARDN_HUB_DATABASE_URL"
    }
    for key, value in required_without_database.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("WARDN_HUB_DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)
