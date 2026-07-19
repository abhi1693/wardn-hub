from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from redis.asyncio import Redis
from redis.asyncio.sentinel import Sentinel

if TYPE_CHECKING:
    from app.core.config import Settings


@dataclass(frozen=True)
class ValkeyConnectionConfig:
    url: str
    sentinels: str
    sentinel_service: str
    db: int
    password: str
    sentinel_password: str
    socket_timeout_seconds: float
    max_connections: int


def connection_config_from_settings(
    settings: Settings,
    *,
    db: int,
    socket_timeout_seconds: float,
    max_connections: int,
) -> ValkeyConnectionConfig:
    use_generic_settings = bool(settings.valkey_url or settings.valkey_sentinels)
    return ValkeyConnectionConfig(
        url=settings.valkey_url if use_generic_settings else settings.public_rate_limit_valkey_url,
        sentinels=(
            settings.valkey_sentinels
            if use_generic_settings
            else settings.public_rate_limit_valkey_sentinels
        ),
        sentinel_service=(
            settings.valkey_sentinel_service
            if use_generic_settings
            else settings.public_rate_limit_valkey_sentinel_service
        ),
        db=db,
        password=(
            settings.valkey_password
            if use_generic_settings
            else settings.public_rate_limit_valkey_password
        ),
        sentinel_password=(
            settings.valkey_sentinel_password
            if use_generic_settings
            else settings.public_rate_limit_valkey_sentinel_password
        ),
        socket_timeout_seconds=socket_timeout_seconds,
        max_connections=max_connections,
    )


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


def create_async_valkey_client(config: ValkeyConnectionConfig) -> Redis:
    common_options = {
        "socket_timeout": config.socket_timeout_seconds,
        "socket_connect_timeout": config.socket_timeout_seconds,
        "socket_keepalive": True,
        "decode_responses": False,
        "max_connections": config.max_connections,
    }
    if config.url:
        return Redis.from_url(
            normalize_valkey_url(config.url),
            db=config.db,
            password=config.password or None,
            **common_options,
        )

    sentinels = parse_sentinels(config.sentinels, setting_name="valkey_sentinels")
    sentinel_password = config.sentinel_password or None
    sentinel_kwargs = {
        **common_options,
        **({"password": sentinel_password} if sentinel_password else {}),
    }
    sentinel = Sentinel(
        sentinels,
        sentinel_kwargs=sentinel_kwargs,
    )
    return sentinel.master_for(
        config.sentinel_service.strip() or "valkey",
        db=config.db,
        password=config.password or None,
        **common_options,
    )
