from __future__ import annotations

from typing import Any

from app.core.cache import RedisSDKByteCache, cache_key


class FakeCacheBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.expirations: dict[tuple[str, str], int] = {}
        self.fail = False

    async def get(
        self,
        key: str,
        *,
        default: Any = None,
        eviction_group: str | None = None,
    ) -> str | None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        return self.values.get((key, eviction_group or ""), default)

    async def set(
        self,
        key: str,
        value: str,
        *,
        ttl: int | None = None,
        eviction_group: str | None = None,
    ) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.values[(key, eviction_group or "")] = value
        self.expirations[(key, eviction_group or "")] = ttl or 0

    async def delete(self, key: str, *, eviction_group: str | None = None) -> bool:
        if self.fail:
            raise RuntimeError("redis unavailable")
        return self.values.pop((key, eviction_group or ""), None) is not None



def test_cache_key_is_stable_versioned_and_hides_material() -> None:
    first = cache_key(
        "skill-search",
        version=1,
        material={"query": "private search", "limit": 8},
    )
    reordered = cache_key(
        "skill-search",
        version=1,
        material={"limit": 8, "query": "private search"},
    )

    assert first == reordered
    assert first.startswith("skill-search:v1:")
    assert "private" not in first
    assert cache_key("skill-search", version=2, material={"limit": 8}) != first


async def test_redis_sdk_cache_retains_remote_bytes_with_sdk_ttl() -> None:
    backend = FakeCacheBackend()
    cache = RedisSDKByteCache(
        backend_factory=lambda: backend,  # type: ignore[return-value]
        default_ttl_seconds=60,
        max_value_bytes=8,
        eviction_group="skill-search",
    )

    assert await cache.get("search:key") is None
    assert await cache.set("search:key", b"payload") is True
    assert await cache.get("search:key") == b"payload"
    assert backend.values == {("search:key", "skill-search"): "payload"}
    assert backend.expirations == {("search:key", "skill-search"): 60}

    await cache.delete("search:key")
    assert backend.values == {}
    await cache.close()


async def test_redis_sdk_cache_skips_oversized_values_and_fails_open() -> None:
    backend = FakeCacheBackend()
    cache = RedisSDKByteCache(
        backend_factory=lambda: backend,  # type: ignore[return-value]
        default_ttl_seconds=60,
        max_value_bytes=4,
        eviction_group="skill-search",
    )

    assert await cache.set("key", b"oversized") is False
    assert backend.values == {}

    backend.fail = True
    assert await cache.get("key") is None
    assert await cache.set("key", b"safe") is False
    await cache.delete("key")
