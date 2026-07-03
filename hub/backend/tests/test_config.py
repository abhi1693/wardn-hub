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


def test_auth_providers_parse_comma_separated_env(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_AUTH_PROVIDERS": "local, clerk",
            "WARDN_HUB_AUTH_DEFAULT_PROVIDER": "clerk",
        },
    )

    settings = Settings(_env_file=None)

    assert settings.auth_providers == ["local", "clerk"]
    assert settings.auth_default_provider == "clerk"


def test_auth_default_provider_must_be_enabled(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_AUTH_PROVIDERS": "local",
            "WARDN_HUB_AUTH_DEFAULT_PROVIDER": "clerk",
        },
    )

    with pytest.raises(ValidationError, match="auth_default_provider"):
        Settings(_env_file=None)


def test_production_clerk_auth_requires_issuer(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_ENVIRONMENT": "production",
            "WARDN_HUB_SESSION_SECRET": "s" * 32,
            "WARDN_HUB_API_TOKEN_SECRET": "t" * 32,
            "WARDN_HUB_AUTH_PROVIDERS": "clerk",
            "WARDN_HUB_AUTH_DEFAULT_PROVIDER": "clerk",
        },
    )

    with pytest.raises(ValidationError, match="clerk_issuer"):
        Settings(_env_file=None)


def test_database_url_is_required_without_env(monkeypatch) -> None:
    required_without_database = {
        key: value for key, value in REQUIRED_SETTINGS.items() if key != "WARDN_HUB_DATABASE_URL"
    }
    for key, value in required_without_database.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("WARDN_HUB_DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_release_environment_rejects_placeholder_secrets(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_ENVIRONMENT": "production",
            "WARDN_HUB_SESSION_SECRET": "change-me",
            "WARDN_HUB_API_TOKEN_SECRET": "change-me",
        },
    )

    with pytest.raises(ValidationError, match="session_secret"):
        Settings(_env_file=None)


def test_release_environment_rejects_placeholder_system_review_secret(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_ENVIRONMENT": "production",
            "WARDN_HUB_SESSION_SECRET": "s" * 32,
            "WARDN_HUB_API_TOKEN_SECRET": "t" * 32,
            "WARDN_HUB_SYSTEM_REVIEW_SECRET": "secret",
        },
    )

    with pytest.raises(ValidationError, match="system_review_secret"):
        Settings(_env_file=None)


def test_release_environment_rejects_wildcard_cors(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_ENVIRONMENT": "production",
            "WARDN_HUB_SESSION_SECRET": "s" * 32,
            "WARDN_HUB_API_TOKEN_SECRET": "t" * 32,
            "WARDN_HUB_CORS_ORIGINS": "*",
        },
    )

    with pytest.raises(ValidationError, match="cors_origins"):
        Settings(_env_file=None)


def test_release_environment_accepts_strong_secrets(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_ENVIRONMENT": "production",
            "WARDN_HUB_SESSION_SECRET": "s" * 32,
            "WARDN_HUB_API_TOKEN_SECRET": "t" * 32,
            "WARDN_HUB_CORS_ORIGINS": "https://hub.example.com",
        },
    )

    settings = Settings(_env_file=None)

    assert settings.environment == "production"
    assert settings.cors_origins == ["https://hub.example.com"]


def test_api_prefix_must_be_normalized(monkeypatch) -> None:
    set_required_settings(monkeypatch, {"WARDN_HUB_API_PREFIX": "api/v1/"})

    with pytest.raises(ValidationError, match="api_prefix"):
        Settings(_env_file=None)


def test_otel_settings_default_to_disabled(monkeypatch) -> None:
    set_required_settings(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.otel_enabled is False
    assert settings.otel_service_name == "wardn-hub-api"
    assert settings.otel_service_namespace == "wardn-hub"
    assert settings.otel_traces_sample_ratio == 1.0


def test_otel_trace_sample_ratio_must_be_between_zero_and_one(monkeypatch) -> None:
    set_required_settings(monkeypatch, {"WARDN_HUB_OTEL_TRACES_SAMPLE_RATIO": "1.1"})

    with pytest.raises(ValidationError, match="otel_traces_sample_ratio"):
        Settings(_env_file=None)


def test_public_rate_limit_defaults_to_disabled(monkeypatch) -> None:
    set_required_settings(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.public_rate_limit_enabled is False
    assert settings.public_rate_limit_requests == 120
    assert settings.public_rate_limit_window_seconds == 60
    assert settings.public_rate_limit_valkey_db == 5


def test_public_rate_limit_requires_valkey_when_enabled(monkeypatch) -> None:
    set_required_settings(monkeypatch, {"WARDN_HUB_PUBLIC_RATE_LIMIT_ENABLED": "true"})

    with pytest.raises(ValidationError, match="public_rate_limit_valkey"):
        Settings(_env_file=None)


def test_public_rate_limit_accepts_valkey_sentinels_when_enabled(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_PUBLIC_RATE_LIMIT_ENABLED": "true",
            "WARDN_HUB_PUBLIC_RATE_LIMIT_VALKEY_SENTINELS": "valkey.valkey.svc:26379",
        },
    )

    settings = Settings(_env_file=None)

    assert settings.public_rate_limit_enabled is True
    assert settings.public_rate_limit_valkey_sentinels == "valkey.valkey.svc:26379"


def test_public_rate_limit_values_must_be_positive(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_PUBLIC_RATE_LIMIT_REQUESTS": "0",
            "WARDN_HUB_PUBLIC_RATE_LIMIT_WINDOW_SECONDS": "60",
        },
    )

    with pytest.raises(ValidationError, match="public_rate_limit_requests"):
        Settings(_env_file=None)
