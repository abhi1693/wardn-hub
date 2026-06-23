from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.registry import service
from app.modules.registry.exceptions import (
    DuplicateRegistryVersionError,
    InvalidRegistryCursorError,
    RegistryVersionNotFoundError,
)
from app.modules.registry.models import RegistryServer, RegistryServerVersion
from app.modules.registry.schemas import RegistryServerVersionCreate


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = False
        self.refreshed: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushed = True

    async def refresh(self, instance) -> None:
        now = datetime(2026, 6, 23, tzinfo=UTC)
        if getattr(instance, "id", None) is None:
            instance.id = uuid4()
        if getattr(instance, "created_at", None) is None:
            instance.created_at = now
        if getattr(instance, "updated_at", None) is None:
            instance.updated_at = now
        if hasattr(instance, "published_at") and getattr(instance, "published_at", None) is None:
            instance.published_at = now
        if (
            hasattr(instance, "status_changed_at")
            and getattr(instance, "status_changed_at", None) is None
        ):
            instance.status_changed_at = now
        self.refreshed.append(instance)


def registry_payload(version: str = "1.0.0") -> RegistryServerVersionCreate:
    return RegistryServerVersionCreate(
        **{
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "io.github.example/weather",
            "title": "Weather",
            "description": "Weather tools for forecasts",
            "version": version,
            "packages": [
                {
                    "registryType": "npm",
                    "identifier": "@example/weather-mcp",
                    "version": version,
                    "transport": {"type": "stdio"},
                }
            ],
        }
    )


def server_model() -> RegistryServer:
    now = datetime(2026, 6, 23, tzinfo=UTC)
    return RegistryServer(
        id=uuid4(),
        name="io.github.example/weather",
        title="Weather",
        description="Weather tools for forecasts",
        website_url="",
        repository=None,
        icons=[],
        status="active",
        status_message="",
        visibility="public",
        created_at=now,
        updated_at=now,
    )


def version_model(server_id, version: str, *, is_latest: bool) -> RegistryServerVersion:
    now = datetime(2026, 6, 23, tzinfo=UTC)
    payload = registry_payload(version)
    return RegistryServerVersion(
        id=uuid4(),
        server_id=server_id,
        **service.document_values(payload),
        status="active",
        status_message="",
        is_latest=is_latest,
        published_at=now,
        status_changed_at=now,
        created_at=now,
        updated_at=now,
    )


def test_parse_cursor() -> None:
    assert service.parse_cursor(None) == 0
    assert service.parse_cursor("25") == 25

    with pytest.raises(InvalidRegistryCursorError):
        service.parse_cursor("-1")

    with pytest.raises(InvalidRegistryCursorError):
        service.parse_cursor("not-a-cursor")


@pytest.mark.asyncio
async def test_create_server_version_creates_server_and_latest(monkeypatch) -> None:
    calls: list[str] = []

    async def missing_server(*args, **kwargs):
        return None

    async def clear_latest(*args, **kwargs):
        calls.append("clear_latest")

    monkeypatch.setattr(service.repository, "get_server", missing_server)
    monkeypatch.setattr(service.repository, "get_server_version", missing_server)
    monkeypatch.setattr(service.repository, "clear_latest_for_server", clear_latest)

    response = await service.create_server_version(FakeSession(), registry_payload())

    assert calls == ["clear_latest"]
    assert response.server.name == "io.github.example/weather"
    assert response.server.latest_version is not None
    assert response.server.latest_version.version == "1.0.0"
    assert response.version.is_latest is True
    assert response.version.server_json["name"] == "io.github.example/weather"


@pytest.mark.asyncio
async def test_create_server_version_rejects_duplicate(monkeypatch) -> None:
    server = server_model()
    existing = version_model(server.id, "1.0.0", is_latest=True)

    async def existing_version(*args, **kwargs):
        return existing

    monkeypatch.setattr(service.repository, "get_server_version", existing_version)

    with pytest.raises(DuplicateRegistryVersionError):
        await service.create_server_version(FakeSession(), registry_payload())


@pytest.mark.asyncio
async def test_delete_latest_promotes_replacement(monkeypatch) -> None:
    server = server_model()
    latest = version_model(server.id, "2.0.0", is_latest=True)
    replacement = version_model(server.id, "1.0.0", is_latest=False)

    async def get_version(*args, **kwargs):
        return latest

    async def get_server_by_id(*args, **kwargs):
        return server

    async def latest_visible(*args, **kwargs):
        return replacement

    monkeypatch.setattr(service.repository, "get_server_version", get_version)
    monkeypatch.setattr(service.repository, "get_server_by_id", get_server_by_id)
    monkeypatch.setattr(service.repository, "latest_visible_version", latest_visible)

    await service.delete_server_version(FakeSession(), "io.github.example/weather", "2.0.0")

    assert latest.status == "deleted"
    assert latest.is_latest is False
    assert replacement.is_latest is True
    assert server.current_version_id == replacement.id
    assert server.title == replacement.title


@pytest.mark.asyncio
async def test_update_rejects_path_mismatch() -> None:
    with pytest.raises(RegistryVersionNotFoundError):
        await service.update_server_version(
            FakeSession(),
            "io.github.example/weather",
            "1.0.0",
            registry_payload("2.0.0"),
        )
