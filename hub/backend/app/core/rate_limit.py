from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Protocol

from redis.asyncio import Redis
from redis.asyncio.sentinel import Sentinel
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


class ValkeyClient(Protocol):
    async def incr(self, name: str) -> int: ...

    async def expire(self, name: str, time: int) -> object: ...

    async def aclose(self) -> object: ...


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_at: int
    retry_after: int


def parse_sentinels(value: str, *, setting_name: str) -> list[tuple[str, int]]:
    sentinels: list[tuple[str, int]] = []
    for item in value.split(","):
        raw = item.strip()
        if not raw:
            continue
        host, separator, port_value = raw.rpartition(":")
        if not separator or not host or not port_value:
            raise ValueError(f"{setting_name} entries must use host:port")
        try:
            port = int(port_value)
        except ValueError as exc:
            raise ValueError(f"{setting_name} entries must use numeric ports") from exc
        sentinels.append((host, port))
    return sentinels


def normalize_valkey_url(url: str) -> str:
    if url.startswith("valkey://"):
        return f"redis://{url.removeprefix('valkey://')}"
    if url.startswith("valkeys://"):
        return f"rediss://{url.removeprefix('valkeys://')}"
    return url


def public_rate_limit_path_prefixes(api_prefix: str) -> tuple[str, ...]:
    normalized_api_prefix = api_prefix.rstrip("/")
    return tuple(
        f"{normalized_api_prefix}{path_prefix}"
        for path_prefix in DEFAULT_PUBLIC_RATE_LIMIT_PREFIXES
    )


def is_public_rate_limited_request(method: str, path: str, *, api_prefix: str) -> bool:
    if method.upper() not in PUBLIC_RATE_LIMIT_METHODS:
        return False
    return any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in public_rate_limit_path_prefixes(api_prefix)
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


def rate_limit_headers(decision: RateLimitDecision) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(decision.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
        "X-RateLimit-Reset": str(decision.reset_at),
    }


class FixedWindowValkeyRateLimiter:
    def __init__(
        self,
        *,
        client: ValkeyClient,
        limit: int,
        window_seconds: int,
        key_prefix: str,
    ) -> None:
        self.client = client
        self.limit = limit
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix.rstrip(":")

    @classmethod
    def from_settings(cls, settings: Settings) -> FixedWindowValkeyRateLimiter | None:
        if not settings.public_rate_limit_enabled:
            return None

        socket_timeout = settings.public_rate_limit_valkey_socket_timeout_seconds
        if settings.public_rate_limit_valkey_url:
            client = Redis.from_url(
                normalize_valkey_url(settings.public_rate_limit_valkey_url),
                db=settings.public_rate_limit_valkey_db,
                password=settings.public_rate_limit_valkey_password or None,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_timeout,
                socket_keepalive=True,
                decode_responses=True,
            )
        else:
            sentinels = parse_sentinels(
                settings.public_rate_limit_valkey_sentinels,
                setting_name="public_rate_limit_valkey_sentinels",
            )
            sentinel_password = settings.public_rate_limit_valkey_sentinel_password or None
            redis_password = settings.public_rate_limit_valkey_password or None
            sentinel_kwargs = {"password": sentinel_password} if sentinel_password else None
            sentinel = Sentinel(
                sentinels,
                socket_timeout=socket_timeout,
                sentinel_kwargs=sentinel_kwargs,
            )
            client = sentinel.master_for(
                settings.public_rate_limit_valkey_sentinel_service.strip() or "valkey",
                db=settings.public_rate_limit_valkey_db,
                password=redis_password,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_timeout,
                socket_keepalive=True,
                decode_responses=True,
            )

        return cls(
            client=client,
            limit=settings.public_rate_limit_requests,
            window_seconds=settings.public_rate_limit_window_seconds,
            key_prefix=settings.public_rate_limit_key_prefix,
        )

    async def check(self, identifier: str, *, now: float | None = None) -> RateLimitDecision:
        current_time = time.time() if now is None else now
        window_start = int(current_time // self.window_seconds) * self.window_seconds
        reset_at = window_start + self.window_seconds
        retry_after = max(1, reset_at - int(current_time))
        key = self._key(identifier, window_start)

        count = await self.client.incr(key)
        if count == 1:
            await self.client.expire(key, self.window_seconds + 1)

        remaining = max(0, self.limit - count)
        return RateLimitDecision(
            allowed=count <= self.limit,
            limit=self.limit,
            remaining=remaining,
            reset_at=reset_at,
            retry_after=retry_after,
        )

    async def close(self) -> None:
        await self.client.aclose()

    def _key(self, identifier: str, window_start: int) -> str:
        identifier_hash = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
        return f"{self.key_prefix}:{window_start}:{identifier_hash}"


class PublicAPIRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: object,
        *,
        settings: Settings,
        limiter: FixedWindowValkeyRateLimiter,
    ) -> None:
        super().__init__(app)
        self.settings = settings
        self.limiter = limiter

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if not is_public_rate_limited_request(
            request.method,
            request.url.path,
            api_prefix=self.settings.api_prefix,
        ):
            return await call_next(request)

        identifier = client_identifier(
            request,
            trust_forwarded_for=self.settings.public_rate_limit_trust_forwarded_for,
        )
        try:
            decision = await self.limiter.check(identifier)
        except Exception:
            logger.warning("public API rate limit check failed", exc_info=True)
            return await call_next(request)

        headers = rate_limit_headers(decision)
        if not decision.allowed:
            headers["Retry-After"] = str(decision.retry_after)
            return JSONResponse(
                {"detail": "rate limit exceeded"},
                status_code=429,
                headers=headers,
            )

        response = await call_next(request)
        for name, value in headers.items():
            response.headers.setdefault(name, value)
        return response
