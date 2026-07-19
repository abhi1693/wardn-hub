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


def test_skill_audit_gate_defaults_off_and_can_be_enabled(monkeypatch) -> None:
    set_required_settings(monkeypatch)
    monkeypatch.delenv("WARDN_HUB_SKILL_AUDIT_ENABLED", raising=False)
    assert Settings(_env_file=None).skill_audit_enabled is False

    monkeypatch.setenv("WARDN_HUB_SKILL_AUDIT_ENABLED", "true")
    assert Settings(_env_file=None).skill_audit_enabled is True


def test_skill_audit_llm_gate_defaults_off_and_can_be_enabled(monkeypatch) -> None:
    set_required_settings(monkeypatch)
    monkeypatch.delenv("WARDN_HUB_SKILL_AUDIT_LLM_ENABLED", raising=False)
    assert Settings(_env_file=None).skill_audit_llm_enabled is False

    monkeypatch.setenv("WARDN_HUB_SKILL_AUDIT_LLM_ENABLED", "true")
    assert Settings(_env_file=None).skill_audit_llm_enabled is True


def test_auth_providers_parse_comma_separated_env(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_AUTH_PROVIDERS": "local, oidc",
            "WARDN_HUB_AUTH_DEFAULT_PROVIDER": "oidc",
        },
    )

    settings = Settings(_env_file=None)

    assert settings.auth_providers == ["local", "oidc"]
    assert settings.auth_default_provider == "oidc"


def test_auth_default_provider_must_be_enabled(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_AUTH_PROVIDERS": "local",
            "WARDN_HUB_AUTH_DEFAULT_PROVIDER": "oidc",
        },
    )

    with pytest.raises(ValidationError, match="auth_default_provider"):
        Settings(_env_file=None)


def test_production_oidc_auth_requires_provider_credentials(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_ENVIRONMENT": "production",
            "WARDN_HUB_SESSION_SECRET": "s" * 32,
            "WARDN_HUB_API_TOKEN_SECRET": "t" * 32,
            "WARDN_HUB_AUTH_PROVIDERS": "oidc",
            "WARDN_HUB_AUTH_DEFAULT_PROVIDER": "oidc",
        },
    )

    with pytest.raises(ValidationError, match="oidc_issuer_url"):
        Settings(_env_file=None)


def test_production_oidc_auth_accepts_provider_credentials(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_ENVIRONMENT": "production",
            "WARDN_HUB_SESSION_SECRET": "s" * 32,
            "WARDN_HUB_API_TOKEN_SECRET": "t" * 32,
            "WARDN_HUB_AUTH_PROVIDERS": "oidc",
            "WARDN_HUB_AUTH_DEFAULT_PROVIDER": "oidc",
            "WARDN_HUB_OIDC_ISSUER_URL": "https://identity.example.com",
            "WARDN_HUB_OIDC_CLIENT_ID": "wardn-hub",
            "WARDN_HUB_OIDC_CLIENT_SECRET": "oidc-secret",
            "WARDN_HUB_REGISTRY_PUBLIC_BASE_URL": "https://hub.example.com",
        },
    )

    settings = Settings(_env_file=None)

    assert settings.auth_providers == ["oidc"]
    assert settings.oidc_issuer_url == "https://identity.example.com"


def test_production_oidc_rejects_plaintext_provider_urls(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_ENVIRONMENT": "production",
            "WARDN_HUB_SESSION_SECRET": "s" * 32,
            "WARDN_HUB_API_TOKEN_SECRET": "t" * 32,
            "WARDN_HUB_AUTH_PROVIDERS": "oidc",
            "WARDN_HUB_AUTH_DEFAULT_PROVIDER": "oidc",
            "WARDN_HUB_OIDC_ISSUER_URL": "http://identity.example.com",
            "WARDN_HUB_OIDC_CLIENT_ID": "wardn-hub",
            "WARDN_HUB_OIDC_CLIENT_SECRET": "oidc-secret",
            "WARDN_HUB_REGISTRY_PUBLIC_BASE_URL": "https://hub.example.com",
        },
    )

    with pytest.raises(ValidationError, match="oidc_issuer_url.*HTTPS"):
        Settings(_env_file=None)


def test_production_oidc_rejects_plaintext_frontend_with_explicit_https_callback(
    monkeypatch,
) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_ENVIRONMENT": "production",
            "WARDN_HUB_SESSION_SECRET": "s" * 32,
            "WARDN_HUB_API_TOKEN_SECRET": "t" * 32,
            "WARDN_HUB_AUTH_PROVIDERS": "oidc",
            "WARDN_HUB_AUTH_DEFAULT_PROVIDER": "oidc",
            "WARDN_HUB_OIDC_ISSUER_URL": "https://identity.example.com",
            "WARDN_HUB_OIDC_CLIENT_ID": "wardn-hub",
            "WARDN_HUB_OIDC_CLIENT_SECRET": "oidc-secret",
            "WARDN_HUB_OIDC_REDIRECT_URI": "https://hub.example.com/api/auth/oidc/callback",
            "WARDN_HUB_REGISTRY_PUBLIC_BASE_URL": "http://hub.example.com",
        },
    )

    with pytest.raises(ValidationError, match="registry_public_base_url.*HTTPS"):
        Settings(_env_file=None)


def test_local_oidc_still_requires_absolute_http_url(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_AUTH_PROVIDERS": "oidc",
            "WARDN_HUB_AUTH_DEFAULT_PROVIDER": "oidc",
            "WARDN_HUB_OIDC_ISSUER_URL": "identity.local",
        },
    )

    with pytest.raises(ValidationError, match="oidc_issuer_url.*absolute HTTP"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "WARDN_HUB_OIDC_ISSUER_URL": "http://identity.local?tenant=wardn",
            },
            "oidc_issuer_url",
        ),
        (
            {
                "WARDN_HUB_OIDC_ISSUER_URL": "http://identity.local",
                "WARDN_HUB_REGISTRY_PUBLIC_BASE_URL": "http://localhost:3000?tenant=wardn",
            },
            "registry_public_base_url",
        ),
    ],
)
def test_oidc_issuer_and_frontend_base_reject_query_strings(
    monkeypatch,
    overrides: dict[str, str],
    message: str,
) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_AUTH_PROVIDERS": "oidc",
            "WARDN_HUB_AUTH_DEFAULT_PROVIDER": "oidc",
            **overrides,
        },
    )

    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None)


def test_oidc_email_lists_parse_and_normalize(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_OIDC_ALLOWED_EMAIL_DOMAINS": "@Example.COM, staff.example.com",
            "WARDN_HUB_OIDC_SUPERUSER_EMAILS": "ADMIN@Example.COM, root@example.com",
        },
    )

    settings = Settings(_env_file=None)

    assert settings.oidc_allowed_email_domains == ["example.com", "staff.example.com"]
    assert settings.oidc_superuser_emails == ["admin@example.com", "root@example.com"]


def test_oidc_state_cookie_must_not_replace_session_cookie(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_AUTH_PROVIDERS": "oidc",
            "WARDN_HUB_AUTH_DEFAULT_PROVIDER": "oidc",
            "WARDN_HUB_SESSION_COOKIE_NAME": "same-cookie",
            "WARDN_HUB_OIDC_STATE_COOKIE_NAME": "same-cookie",
        },
    )

    with pytest.raises(ValidationError, match="cookie_name.*must be different"):
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


def test_database_client_pool_defaults_to_enabled(monkeypatch) -> None:
    set_required_settings(monkeypatch)
    monkeypatch.delenv("WARDN_HUB_DATABASE_CLIENT_POOL_ENABLED", raising=False)

    settings = Settings(_env_file=None)

    assert settings.database_client_pool_enabled is True


def test_database_client_pool_can_be_disabled(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {"WARDN_HUB_DATABASE_CLIENT_POOL_ENABLED": "false"},
    )

    settings = Settings(_env_file=None)

    assert settings.database_client_pool_enabled is False


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
    assert settings.skill_telemetry_rate_limit_requests == 20
    assert settings.skill_telemetry_rate_limit_window_seconds == 60


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
