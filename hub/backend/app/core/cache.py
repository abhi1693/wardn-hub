from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from redis_fastapi import CacheBackend

logger = logging.getLogger(__name__)


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


class RedisSDKByteCache:
    def __init__(
        self,
        *,
        backend_factory: Callable[[], CacheBackend],
        default_ttl_seconds: int,
        max_value_bytes: int,
        eviction_group: str,
    ) -> None:
        self.backend_factory = backend_factory
        self.default_ttl_seconds = default_ttl_seconds
        self.max_value_bytes = max_value_bytes
        self.eviction_group = eviction_group.strip().strip(":")

    async def get(self, key: str) -> bytes | None:
        try:
            value = await self.backend_factory().get(
                key,
                eviction_group=self.eviction_group,
            )
            if value is None:
                return None
            payload = self._to_bytes(value)
            if payload is None or len(payload) > self.max_value_bytes:
                logger.debug("redis sdk cache returned an invalid or oversized value")
                return None
            return payload
        except Exception:
            logger.debug("redis sdk cache read failed; treating as a miss", exc_info=True)
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
            payload = value.decode("utf-8")
            await self.backend_factory().set(
                key,
                payload,
                ttl=ttl,
                eviction_group=self.eviction_group,
            )
            return True
        except Exception:
            logger.debug("redis sdk cache write failed; continuing without caching", exc_info=True)
            return False

    async def delete(self, key: str) -> None:
        try:
            await self.backend_factory().delete(key, eviction_group=self.eviction_group)
        except Exception:
            logger.debug("redis sdk cache delete failed; relying on TTL", exc_info=True)

    async def close(self) -> None:
        return None

    @staticmethod
    def _to_bytes(value: Any) -> bytes | None:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
        return None
