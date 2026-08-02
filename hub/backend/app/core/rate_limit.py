from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable

from redis_fastapi import RateLimitBackend, RateLimitResult
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings

logger = logging.getLogger(__name__)

PUBLIC_RATE_LIMIT_METHODS = {"GET", "HEAD"}
DEFAULT_PUBLIC_RATE_LIMIT_PREFIXES = (
    "/mcp/catalog",
    "/mcp/categories",
    "/mcp/servers",
    "/mcp/badges",
)
ROOT_PUBLIC_RATE_LIMIT_PREFIXES = ("/v0.1/servers",)
SKILL_TELEMETRY_RATE_LIMIT_METHODS = {"POST"}
SKILL_TELEMETRY_RATE_LIMIT_PREFIX = "/skills/telemetry"
MCP_SERVER_TELEMETRY_RATE_LIMIT_PREFIX = "/mcp/servers/telemetry"


def public_rate_limit_path_prefixes(api_prefix: str) -> tuple[str, ...]:
    normalized_api_prefix = api_prefix.rstrip("/")
    api_prefixed = tuple(
        f"{normalized_api_prefix}{path_prefix}"
        for path_prefix in DEFAULT_PUBLIC_RATE_LIMIT_PREFIXES
    )
    return ROOT_PUBLIC_RATE_LIMIT_PREFIXES + api_prefixed


def is_public_rate_limited_request(method: str, path: str, *, api_prefix: str) -> bool:
    if method.upper() not in PUBLIC_RATE_LIMIT_METHODS:
        return False
    return any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in public_rate_limit_path_prefixes(api_prefix)
    )


def is_skill_telemetry_rate_limited_request(
    method: str,
    path: str,
    *,
    api_prefix: str,
) -> bool:
    if method.upper() not in SKILL_TELEMETRY_RATE_LIMIT_METHODS:
        return False
    prefix = f"{api_prefix.rstrip('/')}{SKILL_TELEMETRY_RATE_LIMIT_PREFIX}"
    return path == prefix or path.startswith(f"{prefix}/")


def is_mcp_server_telemetry_rate_limited_request(
    method: str,
    path: str,
    *,
    api_prefix: str,
) -> bool:
    if method.upper() not in SKILL_TELEMETRY_RATE_LIMIT_METHODS:
        return False
    prefix = f"{api_prefix.rstrip('/')}{MCP_SERVER_TELEMETRY_RATE_LIMIT_PREFIX}"
    return path == prefix or path.startswith(f"{prefix}/")


def is_install_telemetry_rate_limited_request(
    method: str,
    path: str,
    *,
    api_prefix: str,
) -> bool:
    return is_skill_telemetry_rate_limited_request(
        method,
        path,
        api_prefix=api_prefix,
    ) or is_mcp_server_telemetry_rate_limited_request(
        method,
        path,
        api_prefix=api_prefix,
    )


def client_identifier(request: Request, *, trust_forwarded_for: bool) -> str:
    if trust_forwarded_for:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        first_forwarded_for = forwarded_for.split(",", 1)[0].strip()
        if first_forwarded_for:
            return first_forwarded_for

    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def rate_limit_headers(result: RateLimitResult) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(result.limit),
        "X-RateLimit-Remaining": str(result.remaining),
        "X-RateLimit-Reset": str(result.reset_at),
    }


def rate_limit_scope(value: str) -> str:
    return value.strip().strip(":")


def rate_limit_identifier(request: Request, *, trust_forwarded_for: bool) -> str:
    identifier = client_identifier(request, trust_forwarded_for=trust_forwarded_for)
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()


class RequestRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: object,
        *,
        settings: Settings,
        backend: RateLimitBackend,
        request_matcher: Callable[[str, str], bool],
        limit: int,
        window_seconds: int,
        scope: str,
        fail_closed: bool,
    ) -> None:
        super().__init__(app)
        self.settings = settings
        self.backend = backend
        self.request_matcher = request_matcher
        self.limit = limit
        self.window_seconds = window_seconds
        self.scope = rate_limit_scope(scope)
        self.fail_closed = fail_closed

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if not self.request_matcher(request.method, request.url.path):
            return await call_next(request)

        identifier = rate_limit_identifier(
            request,
            trust_forwarded_for=self.settings.public_rate_limit_trust_forwarded_for,
        )
        try:
            result = await self.backend.hit(
                identifier,
                limit=self.limit,
                window=self.window_seconds,
                scope=self.scope,
                fail_closed=self.fail_closed,
            )
        except Exception:
            logger.warning("request rate limit check failed", exc_info=True)
            if self.fail_closed:
                return self._backend_unavailable_response()
            return await call_next(request)

        if result.degraded:
            if self.fail_closed:
                return self._backend_unavailable_response()
            return await call_next(request)

        headers = rate_limit_headers(result)
        if not result.allowed:
            headers["Retry-After"] = str(result.retry_after)
            return JSONResponse(
                {"detail": "rate limit exceeded"},
                status_code=429,
                headers=headers,
            )

        response = await call_next(request)
        for name, value in headers.items():
            response.headers.setdefault(name, value)
        return response

    @staticmethod
    def _backend_unavailable_response() -> JSONResponse:
        return JSONResponse(
            {"detail": "telemetry temporarily unavailable"},
            status_code=503,
        )


class PublicAPIRateLimitMiddleware(RequestRateLimitMiddleware):
    def __init__(
        self,
        app: object,
        *,
        settings: Settings,
        backend: RateLimitBackend,
    ) -> None:
        super().__init__(
            app,
            settings=settings,
            backend=backend,
            request_matcher=lambda method, path: is_public_rate_limited_request(
                method,
                path,
                api_prefix=settings.api_prefix,
            ),
            limit=settings.public_rate_limit_requests,
            window_seconds=settings.public_rate_limit_window_seconds,
            scope=settings.public_rate_limit_key_prefix,
            fail_closed=False,
        )


class SkillTelemetryRateLimitMiddleware(RequestRateLimitMiddleware):
    def __init__(
        self,
        app: object,
        *,
        settings: Settings,
        backend: RateLimitBackend,
    ) -> None:
        super().__init__(
            app,
            settings=settings,
            backend=backend,
            request_matcher=lambda method, path: is_install_telemetry_rate_limited_request(
                method,
                path,
                api_prefix=settings.api_prefix,
            ),
            limit=settings.skill_telemetry_rate_limit_requests,
            window_seconds=settings.skill_telemetry_rate_limit_window_seconds,
            scope=settings.skill_telemetry_rate_limit_key_prefix,
            fail_closed=True,
        )
