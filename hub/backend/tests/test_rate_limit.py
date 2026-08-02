from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis_fastapi import RateLimitResult
from starlette.requests import Request

from app.core.config import Settings
from app.core.rate_limit import (
    PublicAPIRateLimitMiddleware,
    SkillTelemetryRateLimitMiddleware,
    client_identifier,
    is_mcp_server_telemetry_rate_limited_request,
    is_public_rate_limited_request,
    is_skill_telemetry_rate_limited_request,
)
from app.core.valkey import normalize_valkey_url, parse_sentinels


class FakeRateLimitBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str | None, str], int] = {}
        self.calls: list[dict[str, object]] = []

    async def hit(
        self,
        identifier: str,
        *,
        limit: int,
        window: int,
        scope: str | None = None,
        cost: int = 1,
        fail_closed: bool | None = None,
    ) -> RateLimitResult:
        self.calls.append(
            {
                "identifier": identifier,
                "limit": limit,
                "window": window,
                "scope": scope,
                "cost": cost,
                "fail_closed": fail_closed,
            }
        )
        key = (scope, identifier)
        current = self.values.get(key, 0)
        allowed = current + cost <= limit
        if allowed:
            current += cost
            self.values[key] = current
        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=max(0, limit - current),
            reset_after=60,
            reset_at=123,
            retry_after=60,
            backend="fake",
        )


class FailingRateLimitBackend:
    async def hit(self, *args: object, **kwargs: object) -> object:
        _ = args, kwargs
        raise RuntimeError("redis unavailable")


class DegradedRateLimitBackend:
    def __init__(self, *, allowed: bool) -> None:
        self.allowed = allowed

    async def hit(self, *args: object, **kwargs: object) -> RateLimitResult:
        _ = args, kwargs
        return RateLimitResult(
            allowed=self.allowed,
            limit=10,
            remaining=10 if self.allowed else 0,
            reset_after=60,
            reset_at=123,
            retry_after=60,
            degraded=True,
        )


def test_public_rate_limit_path_scoping() -> None:
    assert is_public_rate_limited_request("GET", "/v0.1/servers", api_prefix="/api/v1")
    assert is_public_rate_limited_request(
        "HEAD",
        "/v0.1/servers/io.github.example/demo/versions/latest",
        api_prefix="/api/v1",
    )
    assert is_public_rate_limited_request("GET", "/api/v1/mcp/catalog", api_prefix="/api/v1")
    assert is_public_rate_limited_request(
        "HEAD",
        "/api/v1/mcp/servers/io.github.example/demo",
        api_prefix="/api/v1",
    )
    assert not is_public_rate_limited_request(
        "POST",
        "/api/v1/mcp/servers/io.github.example/demo/claim",
        api_prefix="/api/v1",
    )
    assert not is_public_rate_limited_request("POST", "/v0.1/servers", api_prefix="/api/v1")
    assert not is_public_rate_limited_request("GET", "/api/v1/health/ready", api_prefix="/api/v1")
    assert is_skill_telemetry_rate_limited_request(
        "POST",
        "/api/v1/skills/telemetry/acme/skills/weather",
        api_prefix="/api/v1",
    )
    assert not is_skill_telemetry_rate_limited_request(
        "GET",
        "/api/v1/skills/telemetry/acme/skills/weather",
        api_prefix="/api/v1",
    )
    assert is_mcp_server_telemetry_rate_limited_request(
        "POST",
        "/api/v1/mcp/servers/telemetry/io.github.example/weather",
        api_prefix="/api/v1",
    )
    assert not is_mcp_server_telemetry_rate_limited_request(
        "GET",
        "/api/v1/mcp/servers/telemetry/io.github.example/weather",
        api_prefix="/api/v1",
    )


def test_normalize_valkey_url_accepts_valkey_scheme() -> None:
    assert normalize_valkey_url("valkey://localhost:6379/5") == "redis://localhost:6379/5"
    assert normalize_valkey_url("valkeys://localhost:6379/5") == "rediss://localhost:6379/5"
    assert normalize_valkey_url("redis://localhost:6379/5") == "redis://localhost:6379/5"


def test_parse_sentinels_requires_host_port_entries() -> None:
    assert parse_sentinels(
        "valkey-0.valkey.svc:26379,valkey-1.valkey.svc:26379",
        setting_name="example",
    ) == [
        ("valkey-0.valkey.svc", 26379),
        ("valkey-1.valkey.svc", 26379),
    ]
    with pytest.raises(ValueError, match="host:port"):
        parse_sentinels("valkey-0.valkey.svc", setting_name="example")
    with pytest.raises(ValueError, match="numeric ports"):
        parse_sentinels("valkey-0.valkey.svc:not-a-port", setting_name="example")


def test_middleware_uses_sdk_backend_and_returns_429_with_rate_limit_headers() -> None:
    app = FastAPI()
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
        public_rate_limit_requests=1,
        public_rate_limit_window_seconds=60,
    )
    backend = FakeRateLimitBackend()
    app.add_middleware(
        PublicAPIRateLimitMiddleware,
        settings=settings,
        backend=backend,  # type: ignore[arg-type]
    )

    @app.get("/api/v1/mcp/catalog")
    async def catalog() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)

    first = client.get("/api/v1/mcp/catalog", headers={"X-Forwarded-For": "198.51.100.10"})
    second = client.get("/api/v1/mcp/catalog", headers={"X-Forwarded-For": "198.51.100.10"})

    assert first.status_code == 200
    assert first.headers["X-RateLimit-Limit"] == "1"
    assert first.headers["X-RateLimit-Remaining"] == "0"
    assert second.status_code == 429
    assert second.json() == {"detail": "rate limit exceeded"}
    assert second.headers["Retry-After"].isdigit()
    assert backend.calls[0]["scope"] == "wardn-hub:public-api-rate-limit"
    assert backend.calls[0]["identifier"] != "198.51.100.10"
    assert backend.calls[0]["fail_closed"] is False


def test_middleware_fails_open_when_redis_sdk_check_fails() -> None:
    app = FastAPI()
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
    )
    app.add_middleware(
        PublicAPIRateLimitMiddleware,
        settings=settings,
        backend=FailingRateLimitBackend(),  # type: ignore[arg-type]
    )

    @app.get("/api/v1/mcp/catalog")
    async def catalog() -> dict[str, bool]:
        return {"ok": True}

    response = TestClient(app).get("/api/v1/mcp/catalog")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_middleware_fails_open_when_redis_sdk_returns_degraded_result() -> None:
    app = FastAPI()
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
    )
    app.add_middleware(
        PublicAPIRateLimitMiddleware,
        settings=settings,
        backend=DegradedRateLimitBackend(allowed=True),  # type: ignore[arg-type]
    )

    @app.get("/api/v1/mcp/catalog")
    async def catalog() -> dict[str, bool]:
        return {"ok": True}

    response = TestClient(app).get("/api/v1/mcp/catalog")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "X-RateLimit-Limit" not in response.headers


def test_skill_telemetry_middleware_fails_closed_when_redis_sdk_check_fails() -> None:
    app = FastAPI()
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
    )
    app.add_middleware(
        SkillTelemetryRateLimitMiddleware,
        settings=settings,
        backend=FailingRateLimitBackend(),  # type: ignore[arg-type]
    )

    @app.post("/api/v1/skills/telemetry/acme/skills/weather")
    async def telemetry() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/v1/mcp/servers/telemetry/io.github.example/weather")
    async def server_telemetry() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    response = client.post("/api/v1/skills/telemetry/acme/skills/weather")
    server_response = client.post("/api/v1/mcp/servers/telemetry/io.github.example/weather")

    assert response.status_code == 503
    assert response.json() == {"detail": "telemetry temporarily unavailable"}
    assert server_response.status_code == 503
    assert server_response.json() == {"detail": "telemetry temporarily unavailable"}


def test_skill_telemetry_middleware_fails_closed_when_redis_sdk_returns_degraded_result() -> None:
    app = FastAPI()
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
    )
    app.add_middleware(
        SkillTelemetryRateLimitMiddleware,
        settings=settings,
        backend=DegradedRateLimitBackend(allowed=False),  # type: ignore[arg-type]
    )

    @app.post("/api/v1/skills/telemetry/acme/skills/weather")
    async def telemetry() -> dict[str, bool]:
        return {"ok": True}

    response = TestClient(app).post("/api/v1/skills/telemetry/acme/skills/weather")

    assert response.status_code == 503
    assert response.json() == {"detail": "telemetry temporarily unavailable"}


async def test_client_identifier_uses_forwarded_for_when_trusted() -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/mcp/catalog",
        "headers": [
            (b"x-forwarded-for", b"198.51.100.10, 203.0.113.20"),
            (b"x-real-ip", b"203.0.113.30"),
        ],
        "client": ("203.0.113.40", 12345),
        "scheme": "http",
        "server": ("testserver", 80),
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        _ = message

    request = Request(
        scope,
        receive=receive,
        send=send,  # type: ignore[arg-type]
    )

    assert client_identifier(request, trust_forwarded_for=True) == "198.51.100.10"
    assert client_identifier(request, trust_forwarded_for=False) == "203.0.113.30"
