from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from typing import Protocol

from app.core.config import Settings
from app.core.valkey import connection_config_from_settings, create_async_valkey_client

logger = logging.getLogger(__name__)


class AsyncValkeyCacheClient(Protocol):
    async def get(self, name: str) -> bytes | None: ...

    async def set(self, name: str, value: bytes, *, ex: int) -> object: ...

    async def delete(self, *names: str) -> object: ...

    async def aclose(self) -> object: ...


class ByteCache(Protocol):
    async def get(self, key: str) -> bytes | None: ...

    async def set(self, key: str, value: bytes, *, ttl_seconds: int | None = None) -> bool: ...

    async def delete(self, key: str) -> None: ...

    async def close(self) -> None: ...


def cache_key(namespace: str, *, version: int, material: Mapping[str, object]) -> str:
    normalized_namespace = namespace.strip().lower()
    if not normalized_namespace or not normalized_namespace.replace("-", "").isalnum():
        raise ValueError("cache namespace must contain letters, numbers, or hyphens")
    if version <= 0:
        raise ValueError("cache key version must be positive")
    encoded = json.dumps(
        material,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"{normalized_namespace}:v{version}:{digest}"


class ValkeyByteCache:
    def __init__(
        self,
        *,
        client: AsyncValkeyCacheClient,
        key_prefix: str,
        default_ttl_seconds: int,
        max_value_bytes: int,
    ) -> None:
        self.client = client
        self.key_prefix = key_prefix.strip().strip(":")
        self.default_ttl_seconds = default_ttl_seconds
        self.max_value_bytes = max_value_bytes

    @classmethod
    def from_settings(cls, settings: Settings) -> ValkeyByteCache:
        client = create_async_valkey_client(
            connection_config_from_settings(
                settings,
                db=settings.cache_valkey_db,
                socket_timeout_seconds=settings.cache_command_timeout_seconds,
                max_connections=settings.cache_max_connections,
            )
        )
        return cls(
            client=client,
            key_prefix=f"{settings.cache_key_prefix}:{settings.environment.strip().lower()}",
            default_ttl_seconds=settings.cache_default_ttl_seconds,
            max_value_bytes=settings.cache_max_value_bytes,
        )

    async def get(self, key: str) -> bytes | None:
        try:
            value = await self.client.get(self._key(key))
            if value is None:
                return None
            if not isinstance(value, bytes) or len(value) > self.max_value_bytes:
                logger.debug("valkey cache returned an invalid or oversized value")
                return None
            return value
        except Exception:
            logger.debug("valkey cache read failed; treating as a miss", exc_info=True)
            return None

    async def set(
        self,
        key: str,
        value: bytes,
        *,
        ttl_seconds: int | None = None,
    ) -> bool:
        if not isinstance(value, bytes) or len(value) > self.max_value_bytes:
            return False
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            raise ValueError("cache TTL must be positive")
        try:
            await self.client.set(self._key(key), value, ex=ttl)
            return True
        except Exception:
            logger.debug("valkey cache write failed; continuing without caching", exc_info=True)
            return False

    async def delete(self, key: str) -> None:
        try:
            await self.client.delete(self._key(key))
        except Exception:
            logger.debug("valkey cache delete failed; relying on TTL", exc_info=True)

    async def close(self) -> None:
        await self.client.aclose()

    def _key(self, key: str) -> str:
        return f"{self.key_prefix}:{key.strip().strip(':')}"
