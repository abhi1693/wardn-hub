from fastapi.testclient import TestClient

from app import main
from app.core.cache import RedisSDKByteCache
from app.core.config import APP_VERSION, Settings
from app.main import create_app


def test_app_metadata() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()

    assert schema["info"] == {
        "title": "Wardn Hub API",
        "version": APP_VERSION,
    }


def test_unversioned_openapi_is_not_exposed() -> None:
    client = TestClient(create_app())

    assert client.get("/openapi.json").status_code == 404


def test_openapi_docs_ui_is_exposed() -> None:
    client = TestClient(create_app())

    swagger = client.get("/api/v1/docs")
    redoc = client.get("/api/v1/redoc")

    assert swagger.status_code == 200
    assert swagger.headers["content-type"].startswith("text/html")
    assert "/api/v1/openapi.json" in swagger.text
    assert redoc.status_code == 200
    assert redoc.headers["content-type"].startswith("text/html")
    assert "/api/v1/openapi.json" in redoc.text


def test_root_docs_routes_redirect_to_versioned_docs_ui() -> None:
    client = TestClient(create_app(), follow_redirects=False)

    docs = client.get("/docs")
    redoc = client.get("/redoc")

    assert docs.status_code == 307
    assert docs.headers["location"] == "/api/v1/docs"
    assert redoc.status_code == 307
    assert redoc.headers["location"] == "/api/v1/redoc"


def test_redis_sdk_resources_preserve_bounded_cache_and_rate_limit_pools(
    monkeypatch,
) -> None:
    settings = Settings(
        environment="local",
        api_prefix="/api/v1",
        log_level="INFO",
        api_token_secret="test-token-secret",
        api_token_prefix="wardn_hub",
        session_cookie_name="wardn_hub_session",
        session_secret="test-session-secret",
        session_ttl_seconds=43200,
        registry_public_base_url="http://localhost:3000",
        database_url="postgresql+asyncpg://user:pass@localhost:5432/wardn_hub",
        valkey_url="valkey://localhost:6379",
        public_rate_limit_enabled=True,
        cache_enabled=True,
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)

    app = main.create_app()
    resources = app.state.redis_sdk_resources

    assert app.state.rate_limit_backend is resources.rate_limit_backend
    assert isinstance(app.state.cache, RedisSDKByteCache)
    assert resources.cache_client is not resources.rate_limit_client
    assert resources.rate_limit_client.connection_pool.connection_kwargs["db"] == 5
    assert resources.rate_limit_client.connection_pool.max_connections == 10
    assert resources.cache_client.connection_pool.connection_kwargs["db"] == 6
    assert resources.cache_client.connection_pool.max_connections == 10
