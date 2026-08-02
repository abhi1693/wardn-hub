from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr
from redis.asyncio import Redis
from redis_fastapi import CacheBackend, RateLimitBackend
from redis_fastapi.config import get_settings as get_redis_sdk_settings

from app.core.config import Settings
from app.core.valkey import (
    ValkeyConnectionConfig,
    connection_config_from_settings,
    create_async_valkey_client,
    normalize_valkey_url,
)


def redis_sdk_key_prefix(settings: Settings) -> str:
    environment = settings.environment.strip().lower() or "local"
    return f"wardn-hub:{environment}"


def cache_sdk_key_prefix(settings: Settings) -> str:
    environment = settings.environment.strip().lower() or "local"
    return f"{settings.cache_key_prefix.strip().strip(':')}:{environment}"


def configure_redis_sdk_settings(
    settings: Settings,
    *,
    prefix: str,
    connection_config: ValkeyConnectionConfig,
) -> None:
    redis_settings = get_redis_sdk_settings()
    redis_settings.url = normalize_valkey_url(connection_config.url) or None
    redis_settings.db = connection_config.db
    redis_settings.password = (
        SecretStr(connection_config.password) if connection_config.password else None
    )
    redis_settings.max_connections = connection_config.max_connections
    redis_settings.socket_timeout = connection_config.socket_timeout_seconds
    redis_settings.socket_connect_timeout = connection_config.socket_timeout_seconds
    redis_settings.cluster = False
    redis_settings.prefix = prefix.strip().strip(":")
    redis_settings.default_ttl = settings.cache_default_ttl_seconds
    redis_settings.rate_limit_default_limit = 0
    redis_settings.rate_limit_default_window = settings.public_rate_limit_window_seconds
    redis_settings.rate_limit_fail_closed = False
    redis_settings.rate_limit_emit_headers = True
    redis_settings.rate_limit_ietf_headers = False
    redis_settings.rate_limit_trust_proxy = settings.public_rate_limit_trust_forwarded_for
    redis_settings.otel_enabled = settings.otel_enabled
    redis_settings.otel_redis_enabled = settings.otel_enabled


@dataclass
class RedisSDKResources:
    cache_client: Redis | None = None
    cache_backend: CacheBackend | None = None
    rate_limit_client: Redis | None = None
    rate_limit_backend: RateLimitBackend | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> RedisSDKResources:
        resources = cls()
        if settings.cache_enabled:
            cache_config = connection_config_from_settings(
                settings,
                db=settings.cache_valkey_db,
                socket_timeout_seconds=settings.cache_command_timeout_seconds,
                max_connections=settings.cache_max_connections,
            )
            configure_redis_sdk_settings(
                settings,
                prefix=cache_sdk_key_prefix(settings),
                connection_config=cache_config,
            )
            resources.cache_client = create_async_valkey_client(cache_config)
            resources.cache_backend = CacheBackend(resources.cache_client)

        if settings.public_rate_limit_enabled:
            rate_limit_config = connection_config_from_settings(
                settings,
                db=settings.public_rate_limit_valkey_db,
                socket_timeout_seconds=(
                    settings.public_rate_limit_valkey_socket_timeout_seconds
                ),
                max_connections=settings.public_rate_limit_valkey_max_connections,
            )
            configure_redis_sdk_settings(
                settings,
                prefix=redis_sdk_key_prefix(settings),
                connection_config=rate_limit_config,
            )
            resources.rate_limit_client = create_async_valkey_client(rate_limit_config)
            resources.rate_limit_backend = RateLimitBackend(resources.rate_limit_client)

        return resources

    async def close(self) -> None:
        closed_clients: set[int] = set()
        for client in (self.cache_client, self.rate_limit_client):
            if client is None or id(client) in closed_clients:
                continue
            closed_clients.add(id(client))
            await client.aclose()
