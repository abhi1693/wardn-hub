from app.core.config import Settings
from app.core.telemetry import _build_resource_attributes, _parse_key_value_pairs

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


def test_parse_key_value_pairs_ignores_invalid_entries() -> None:
    assert _parse_key_value_pairs("a=1, missing, b = two=2, =ignored") == {
        "a": "1",
        "b": "two=2",
    }


def test_build_resource_attributes_includes_service_defaults(monkeypatch) -> None:
    set_required_settings(
        monkeypatch,
        {
            "WARDN_HUB_ENVIRONMENT": "production",
            "WARDN_HUB_SESSION_SECRET": "s" * 32,
            "WARDN_HUB_API_TOKEN_SECRET": "t" * 32,
            "WARDN_HUB_OTEL_SERVICE_NAME": "wardn-hub",
            "WARDN_HUB_OTEL_RESOURCE_ATTRIBUTES": (
                "k8s.namespace.name=wardn,k8s.deployment.name=wardn-hub"
            ),
        },
    )

    settings = Settings(_env_file=None)

    assert _build_resource_attributes(settings) == {
        "service.name": "wardn-hub",
        "service.namespace": "wardn-hub",
        "service.version": settings.app_version,
        "deployment.environment.name": "production",
        "k8s.namespace.name": "wardn",
        "k8s.deployment.name": "wardn-hub",
    }
