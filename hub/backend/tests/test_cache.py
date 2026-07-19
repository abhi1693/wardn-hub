from __future__ import annotations

from app.core.cache import ValkeyByteCache, cache_key


class FakeValkeyCacheClient:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.expirations: dict[str, int] = {}
        self.closed = False
        self.fail = False

    async def get(self, name: str) -> bytes | None:
        if self.fail:
            raise RuntimeError("valkey unavailable")
        return self.values.get(name)

    async def set(self, name: str, value: bytes, *, ex: int) -> bool:
        if self.fail:
            raise RuntimeError("valkey unavailable")
        self.values[name] = value
        self.expirations[name] = ex
        return True

    async def delete(self, *names: str) -> int:
        if self.fail:
            raise RuntimeError("valkey unavailable")
        deleted = 0
        for name in names:
            if name in self.values:
                deleted += 1
                del self.values[name]
        return deleted

    async def aclose(self) -> None:
        self.closed = True


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


async def test_valkey_cache_retains_only_remote_bytes_with_native_ttl() -> None:
    client = FakeValkeyCacheClient()
    cache = ValkeyByteCache(
        client=client,
        key_prefix="wardn-hub:cache:test",
        default_ttl_seconds=60,
        max_value_bytes=8,
    )

    assert await cache.get("search:key") is None
    assert await cache.set("search:key", b"payload") is True
    assert await cache.get("search:key") == b"payload"
    assert client.values == {"wardn-hub:cache:test:search:key": b"payload"}
    assert client.expirations == {"wardn-hub:cache:test:search:key": 60}

    await cache.delete("search:key")
    assert client.values == {}
    await cache.close()
    assert client.closed is True


async def test_valkey_cache_skips_oversized_values_and_fails_open() -> None:
    client = FakeValkeyCacheClient()
    cache = ValkeyByteCache(
        client=client,
        key_prefix="wardn-hub:cache:test",
        default_ttl_seconds=60,
        max_value_bytes=4,
    )

    assert await cache.set("key", b"oversized") is False
    assert client.values == {}

    client.fail = True
    assert await cache.get("key") is None
    assert await cache.set("key", b"safe") is False
    await cache.delete("key")
