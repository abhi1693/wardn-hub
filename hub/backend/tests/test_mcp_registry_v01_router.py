from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app
from app.modules.mcp_registry_v01 import router
from app.modules.registry.exceptions import RegistryServerNotFoundError
from app.modules.registry.schemas import (
    RegistryLatestVersionSummary,
    RegistryListMetadata,
    RegistryServerListResponse,
    RegistryServerRead,
    RegistryServerVersionDetailResponse,
    RegistryServerVersionListResponse,
    RegistryServerVersionRead,
)


async def fake_session():
    yield object()


def registry_server(server_id=None, version_id=None) -> RegistryServerRead:
    server_id = server_id or uuid4()
    version_id = version_id or uuid4()
    return RegistryServerRead(
        id=server_id,
        name="io.github.example/weather",
        title="Weather",
        description="Weather tools",
        documentation="# Weather",
        websiteUrl="https://example.com",
        repository={"url": "https://github.com/example/weather", "source": "github"},
        icons=[{"src": "https://example.com/icon.png", "type": "image/png", "sizes": "64x64"}],
        status="active",
        statusMessage="",
        visibility="public",
        latestVersion=RegistryLatestVersionSummary(
            id=version_id,
            version="1.0.0",
            status="active",
            qualityScore=95,
            publishedAt="2026-06-23T00:00:00Z",
            publishedBy=None,
        ),
        qualityScore=95,
        categories=[],
        partnerSupport=[],
        createdAt="2026-06-23T00:00:00Z",
        updatedAt="2026-06-24T00:00:00Z",
    )


def registry_version(
    version_id=None,
    version="1.0.0",
    *,
    is_latest=True,
) -> RegistryServerVersionRead:
    version_id = version_id or uuid4()
    return RegistryServerVersionRead(
        id=version_id,
        serverId=uuid4(),
        name="io.github.example/weather",
        version=version,
        title="Weather",
        description="Weather tools",
        documentation="# Weather",
        websiteUrl="https://example.com",
        repository={"url": "https://github.com/example/weather", "source": "github"},
        packages=[
            {
                "registryType": "npm",
                "registryBaseUrl": "https://registry.npmjs.org",
                "identifier": "@example/weather",
                "version": version,
                "transport": {"type": "stdio"},
            }
        ],
        remotes=[],
        icons=[{"src": "https://example.com/icon.png", "type": "image/png", "sizes": "64x64"}],
        serverJson={
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "io.github.example/weather",
            "description": "Weather tools",
            "version": version,
            "_meta": {"sourceReview": {"filesRead": ["README.md"]}},
        },
        qualityScore=95,
        status="active",
        statusMessage="",
        isLatest=is_latest,
        partnerSupport=[],
        publishedAt="2026-06-23T00:00:00Z",
        statusChangedAt="2026-06-23T00:00:00Z",
        createdAt="2026-06-23T00:00:00Z",
        updatedAt="2026-06-24T00:00:00Z",
    )


def registry_detail(version="1.0.0", *, is_latest=True) -> RegistryServerVersionDetailResponse:
    version_id = uuid4()
    server_id = uuid4()
    return RegistryServerVersionDetailResponse(
        server=registry_server(server_id, version_id),
        version=registry_version(version_id, version, is_latest=is_latest),
    )


def test_v01_servers_are_public_read_only(monkeypatch) -> None:
    app = create_app()

    async def list_servers(*args, **kwargs):
        return RegistryServerListResponse(
            servers=[],
            metadata=RegistryListMetadata(count=0, nextCursor=""),
        )

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(router, "list_servers", list_servers)

    response = TestClient(app).get("/v0.1/servers")

    assert response.status_code == 200
    assert response.json() == {"servers": [], "metadata": {"count": 0, "nextCursor": ""}}


def test_v01_servers_lists_official_registry_envelope(monkeypatch) -> None:
    app = create_app()
    captured: dict[str, object] = {}

    async def list_servers(*args, **kwargs):
        captured.update(kwargs)
        detail = registry_detail()
        return RegistryServerListResponse(
            servers=[detail.server],
            metadata=RegistryListMetadata(count=1, nextCursor="next-page"),
        )

    async def get_version_detail(*args, **kwargs):
        captured["detail_args"] = args
        return registry_detail()

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(router, "list_servers", list_servers)
    monkeypatch.setattr(router, "get_version_detail", get_version_detail)

    response = TestClient(app).get(
        "/v0.1/servers?limit=10&cursor=start&search=weather&version=latest"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["metadata"] == {"count": 1, "nextCursor": "next-page"}
    assert body["servers"][0]["server"]["name"] == "io.github.example/weather"
    assert body["servers"][0]["server"]["packages"][0]["identifier"] == "@example/weather"
    assert body["servers"][0]["server"]["icons"][0]["mimeType"] == "image/png"
    assert body["servers"][0]["server"]["icons"][0]["sizes"] == ["64x64"]
    assert "sourceReview" not in body["servers"][0]["server"]["_meta"]
    official = body["servers"][0]["_meta"]["io.modelcontextprotocol.registry/official"]
    assert official == {
        "status": "active",
        "statusChangedAt": "2026-06-23T00:00:00Z",
        "publishedAt": "2026-06-23T00:00:00Z",
        "updatedAt": "2026-06-24T00:00:00Z",
        "isLatest": True,
    }
    assert body["servers"][0]["_meta"]["ai.wardn.hub"]["qualityScore"] == 95
    assert captured["cursor"] == "start"
    assert captured["limit"] == 10
    assert captured["search"] == "weather"
    assert captured["version"] == "latest"


def test_v01_server_version_accepts_encoded_server_name(monkeypatch) -> None:
    app = create_app()
    captured: dict[str, object] = {}

    async def get_version_detail(*args):
        captured["args"] = args
        return registry_detail("1.0.0")

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(router, "get_version_detail", get_version_detail)

    response = TestClient(app).get("/v0.1/servers/io.github.example%2Fweather/versions/latest")

    assert response.status_code == 200
    assert captured["args"][1:] == ("io.github.example/weather", "latest")
    assert response.json()["server"]["version"] == "1.0.0"


def test_v01_server_versions_lists_all_versions(monkeypatch) -> None:
    app = create_app()

    async def list_versions(*args):
        return RegistryServerVersionListResponse(
            versions=[
                registry_version(version="1.1.0", is_latest=True),
                registry_version(version="1.0.0", is_latest=False),
            ],
            metadata=RegistryListMetadata(count=2, nextCursor=""),
        )

    async def get_version_detail(*args):
        return registry_detail("1.1.0")

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(router, "list_versions", list_versions)
    monkeypatch.setattr(router, "get_version_detail", get_version_detail)

    response = TestClient(app).get("/v0.1/servers/io.github.example/weather/versions")

    assert response.status_code == 200
    body = response.json()
    assert body["metadata"] == {"count": 2, "nextCursor": ""}
    assert [item["server"]["version"] for item in body["servers"]] == ["1.1.0", "1.0.0"]
    assert body["servers"][0]["_meta"]["io.modelcontextprotocol.registry/official"][
        "isLatest"
    ] is True
    assert body["servers"][1]["_meta"]["io.modelcontextprotocol.registry/official"][
        "isLatest"
    ] is False


def test_v01_server_version_returns_official_error_shape(monkeypatch) -> None:
    app = create_app()

    async def get_version_detail(*args):
        raise RegistryServerNotFoundError("server not found")

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(router, "get_version_detail", get_version_detail)

    response = TestClient(app).get("/v0.1/servers/io.github.example/weather/versions/latest")

    assert response.status_code == 404
    assert response.json() == {"error": "Server not found"}
