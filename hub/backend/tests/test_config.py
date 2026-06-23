from app.core.config import Settings


def test_settings_use_wardn_hub_env_prefix(monkeypatch) -> None:
    monkeypatch.setenv("WARDN_HUB_APP_NAME", "Custom Hub")
    monkeypatch.setenv("WARDN_APP_NAME", "Wrong App")

    settings = Settings()

    assert settings.app_name == "Custom Hub"


def test_cors_origins_parse_comma_separated_env(monkeypatch) -> None:
    monkeypatch.setenv("WARDN_HUB_CORS_ORIGINS", "http://localhost:3000, http://localhost:3001")

    settings = Settings()

    assert settings.cors_origins == ["http://localhost:3000", "http://localhost:3001"]

