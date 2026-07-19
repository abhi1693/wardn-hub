from app.core import valkey


def test_async_valkey_client_uses_sentinel_with_bounded_binary_pool(monkeypatch) -> None:
    captured: dict[str, object] = {}
    expected_client = object()

    class FakeSentinel:
        def __init__(self, sentinels, **kwargs) -> None:
            captured["sentinels"] = sentinels
            captured["sentinel_kwargs"] = kwargs

        def master_for(self, service: str, **kwargs):
            captured["service"] = service
            captured["master_kwargs"] = kwargs
            return expected_client

    monkeypatch.setattr(valkey, "Sentinel", FakeSentinel)

    client = valkey.create_async_valkey_client(
        valkey.ValkeyConnectionConfig(
            url="",
            sentinels="valkey-0.valkey.svc:26379,valkey-1.valkey.svc:26379",
            sentinel_service="wardn-primary",
            db=6,
            password="data-secret",
            sentinel_password="sentinel-secret",
            socket_timeout_seconds=0.25,
            max_connections=10,
        )
    )

    assert client is expected_client
    assert captured["sentinels"] == [
        ("valkey-0.valkey.svc", 26379),
        ("valkey-1.valkey.svc", 26379),
    ]
    assert captured["service"] == "wardn-primary"
    assert captured["sentinel_kwargs"] == {
        "sentinel_kwargs": {
            "socket_timeout": 0.25,
            "socket_connect_timeout": 0.25,
            "socket_keepalive": True,
            "decode_responses": False,
            "max_connections": 10,
            "password": "sentinel-secret",
        },
    }
    assert captured["master_kwargs"] == {
        "db": 6,
        "password": "data-secret",
        "socket_timeout": 0.25,
        "socket_connect_timeout": 0.25,
        "socket_keepalive": True,
        "decode_responses": False,
        "max_connections": 10,
    }
