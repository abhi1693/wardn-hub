from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app
from app.modules.registry import router
from app.modules.registry.exceptions import (
    DuplicateRegistryCategoryError,
    DuplicateRegistryVersionError,
)
from app.modules.registry.schemas import (
    RegistryLatestVersionSummary,
    RegistryListMetadata,
    RegistryOwnershipClaimResponse,
    RegistryPageMetadata,
    RegistryPublishedServerListResponse,
    RegistryServerDetailResponse,
    RegistryServerListResponse,
    RegistryServerRead,
    RegistryServerVersionDetailResponse,
    RegistryServerVersionRead,
)
from app.modules.users import dependencies


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer wardn_hub_key.secret"}


async def catalog_read_session_user():
    return SimpleNamespace(
        id=uuid4(),
        is_active=True,
        is_superuser=False,
        is_global_moderator=False,
        is_global_partner_manager=False,
    )


def allow_catalog_read_session(app) -> None:
    app.dependency_overrides[dependencies.get_current_user] = catalog_read_session_user


def registry_detail_response(server_id, version_id) -> RegistryServerVersionDetailResponse:
    return RegistryServerVersionDetailResponse(
        server=RegistryServerRead(
            id=server_id,
            name="io.github.example/weather",
            title="Weather",
            description="Weather tools",
            documentation="# Large docs",
            websiteUrl="https://example.com",
            repository={"url": "https://github.com/example/weather"},
            icons=[{"src": "https://example.com/icon.png"}],
            status="active",
            statusMessage="",
            visibility="public",
            latestVersion=RegistryLatestVersionSummary(
                id=version_id,
                version="1.0.0",
                status="active",
                qualityScore=96,
                publishedAt="2026-06-23T00:00:00Z",
                publishedBy=None,
            ),
            qualityScore=96,
            categories=[],
            partnerSupport=[],
            createdAt="2026-06-23T00:00:00Z",
            updatedAt="2026-06-23T00:00:00Z",
        ),
        version=RegistryServerVersionRead(
            id=version_id,
            serverId=server_id,
            name="io.github.example/weather",
            version="1.0.0",
            title="Weather",
            description="Weather tools",
            documentation="# Large docs",
            websiteUrl="https://example.com",
            repository={"url": "https://github.com/example/weather"},
            packages=[],
            remotes=[],
            icons=[],
            serverJson={"name": "io.github.example/weather", "version": "1.0.0"},
            qualityScore=96,
            status="active",
            statusMessage="",
            isLatest=True,
            partnerSupport=[],
            publishedAt="2026-06-23T00:00:00Z",
            statusChangedAt="2026-06-23T00:00:00Z",
            createdAt="2026-06-23T00:00:00Z",
            updatedAt="2026-06-23T00:00:00Z",
        ),
    )


async def authenticate_registry_admin_api_token(*args, **kwargs):
    return (
        SimpleNamespace(
            id=uuid4(),
            is_active=True,
            is_superuser=True,
            is_global_moderator=False,
            is_global_partner_manager=False,
        ),
        SimpleNamespace(scopes=["registry:write"]),
    )


async def authenticate_registry_score_api_token(*args, **kwargs):
    return (
        SimpleNamespace(
            id=uuid4(),
            is_active=True,
            is_superuser=True,
            is_global_moderator=False,
            is_global_partner_manager=False,
        ),
        SimpleNamespace(scopes=["registry:score"]),
    )


async def authenticate_registry_write_user_api_token(*args, **kwargs):
    return (
        SimpleNamespace(
            id=uuid4(),
            is_active=True,
            is_superuser=False,
            is_global_moderator=False,
            is_global_partner_manager=False,
        ),
        SimpleNamespace(scopes=["registry:write"]),
    )


async def authenticate_low_scope_api_token(*args, **kwargs):
    return (
        SimpleNamespace(
            id=uuid4(),
            is_active=True,
            is_superuser=False,
            is_global_moderator=False,
            is_global_partner_manager=False,
        ),
        SimpleNamespace(scopes=["catalog:read", "submissions:read", "submissions:write"]),
    )


def test_registry_openapi_exposes_phase_one_paths() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()

    assert {
        "/api/v1/mcp/categories",
        "/api/v1/mcp/badges/quality/{server_name}",
        "/api/v1/mcp/catalog",
        "/api/v1/mcp/servers",
        "/api/v1/mcp/servers/search",
        "/api/v1/mcp/servers/{server_name}",
        "/api/v1/mcp/servers/{server_name}/summary",
        "/api/v1/mcp/servers/{server_name}/tabs/overview",
        "/api/v1/mcp/servers/{server_name}/tabs/schema",
        "/api/v1/mcp/servers/{server_name}/tabs/score",
        "/api/v1/mcp/servers/{server_name}/versions",
        "/api/v1/mcp/servers/{server_name}/versions/{version}",
        "/api/v1/admin/mcp/servers",
        "/api/v1/admin/mcp/servers/{server_name}/versions/{version}",
        "/api/v1/admin/mcp/servers/{server_name}/versions/{version}/quality-score",
        "/api/v1/admin/mcp/servers/{server_name}/versions/{version}/latest",
        "/api/v1/mcp/categories/{category_slug}",
    }.issubset(set(schema["paths"]))
    assert (
        schema["paths"]["/api/v1/mcp/categories"]["get"]["operationId"] == "mcp_categories_list"
    )
    assert (
        schema["paths"]["/api/v1/mcp/categories"]["post"]["operationId"] == "mcp_categories_create"
    )
    assert (
        schema["paths"]["/api/v1/mcp/categories/{category_slug}"]["patch"]["operationId"]
        == "mcp_categories_update"
    )
    assert schema["paths"]["/api/v1/mcp/servers"]["get"]["operationId"] == "mcp_servers_list"
    assert (
        schema["paths"]["/api/v1/mcp/servers/search"]["get"]["operationId"]
        == "mcp_servers_search"
    )
    assert (
        schema["paths"]["/api/v1/mcp/servers/{server_name}/summary"]["get"]["operationId"]
        == "mcp_servers_get_summary"
    )
    assert (
        schema["paths"]["/api/v1/mcp/servers/{server_name}/tabs/overview"]["get"][
            "operationId"
        ]
        == "mcp_servers_get_overview_tab"
    )
    assert (
        schema["paths"]["/api/v1/mcp/servers/{server_name}/tabs/schema"]["get"][
            "operationId"
        ]
        == "mcp_servers_get_schema_tab"
    )
    assert (
        schema["paths"]["/api/v1/mcp/servers/{server_name}/tabs/score"]["get"]["operationId"]
        == "mcp_servers_get_score_tab"
    )
    server_list_params = {
        parameter["name"]
        for parameter in schema["paths"]["/api/v1/mcp/servers"]["get"].get("parameters", [])
    }
    assert "include_deleted" not in server_list_params
    assert "status" not in server_list_params
    for path in (
        "/api/v1/mcp/servers/{server_name}",
        "/api/v1/mcp/servers/{server_name}/versions",
        "/api/v1/mcp/servers/{server_name}/versions/{version}",
    ):
        params = {
            parameter["name"] for parameter in schema["paths"][path]["get"].get("parameters", [])
        }
        assert "include_deleted" not in params
    assert (
        schema["paths"]["/api/v1/mcp/catalog"]["get"]["operationId"]
        == "mcp_catalog_list"
    )
    assert (
        schema["paths"]["/api/v1/mcp/badges/quality/{server_name}"]["get"]["operationId"]
        == "mcp_quality_score_badge"
    )
    assert schema["paths"]["/api/v1/users"]["get"]["operationId"] == "users_list"
    assert schema["paths"]["/api/v1/users/{user_id}"]["get"]["operationId"] == "users_get"
    assert (
        schema["paths"]["/api/v1/admin/mcp/servers"]["post"]["operationId"]
        == "admin_mcp_servers_create_version"
    )
    assert (
        schema["paths"][
            "/api/v1/admin/mcp/servers/{server_name}/versions/{version}/quality-score"
        ]["patch"]["operationId"]
        == "admin_mcp_servers_update_version_quality_score"
    )


def test_published_servers_route_requires_authentication() -> None:
    response = TestClient(create_app()).get("/api/v1/mcp/catalog?page=2")

    assert response.status_code == 401


def test_published_servers_route_accepts_session_and_uses_fixed_page_size(monkeypatch) -> None:
    app = create_app()
    captured: dict[str, int] = {}

    async def fake_session():
        class Session:
            pass

        yield Session()

    async def published_servers(*args, **kwargs):
        captured.update(kwargs)
        return RegistryPublishedServerListResponse(
            servers=[],
            metadata=RegistryPageMetadata(page=2, perPage=20, total=0, pages=0),
        )

    app.dependency_overrides[get_db_session] = fake_session
    allow_catalog_read_session(app)
    monkeypatch.setattr(router, "list_published_servers", published_servers)

    response = TestClient(app).get("/api/v1/mcp/catalog?page=2")

    assert response.status_code == 200
    assert response.json() == {
        "servers": [],
        "metadata": {"page": 2, "perPage": 20, "total": 0, "pages": 0},
    }
    assert captured == {"page": 2, "per_page": 20}


def test_published_servers_route_accepts_catalog_read_api_token(monkeypatch) -> None:
    app = create_app()

    async def fake_session():
        yield object()

    async def published_servers(*args, **kwargs):
        return RegistryPublishedServerListResponse(
            servers=[],
            metadata=RegistryPageMetadata(page=1, perPage=20, total=0, pages=0),
        )

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(dependencies, "authenticate_api_token", authenticate_low_scope_api_token)
    monkeypatch.setattr(router, "list_published_servers", published_servers)

    response = TestClient(app).get("/api/v1/mcp/catalog", headers=auth_headers())

    assert response.status_code == 200


def test_server_list_requires_catalog_read_scope_for_api_token(monkeypatch) -> None:
    app = create_app()

    async def fake_session():
        yield object()

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(
        dependencies,
        "authenticate_api_token",
        authenticate_registry_write_user_api_token,
    )

    response = TestClient(app).get("/api/v1/mcp/servers", headers=auth_headers())

    assert response.status_code == 403
    assert response.json() == {"detail": "API token missing required scope: catalog:read"}


def test_list_servers_route_projects_requested_fields(monkeypatch) -> None:
    app = create_app()
    server_id = uuid4()
    version_id = uuid4()

    async def fake_session():
        class Session:
            pass

        yield Session()

    async def list_servers(*args, **kwargs):
        return RegistryServerListResponse(
            servers=[
                RegistryServerRead(
                    id=server_id,
                    name="io.github.example/weather",
                    title="Weather",
                    description="Weather tools",
                    documentation="# Large docs",
                    websiteUrl="https://example.com",
                    repository={"url": "https://github.com/example/weather"},
                    icons=[{"src": "https://example.com/icon.png"}],
                    status="active",
                    statusMessage="",
                    visibility="public",
                    latestVersion=RegistryLatestVersionSummary(
                        id=version_id,
                        version="1.0.0",
                        status="active",
                        publishedAt="2026-06-23T00:00:00Z",
                        publishedBy=None,
                    ),
                    categories=[],
                    partnerSupport=[],
                    createdAt="2026-06-23T00:00:00Z",
                    updatedAt="2026-06-23T00:00:00Z",
                )
            ],
            metadata=RegistryListMetadata(count=1, nextCursor=""),
        )

    app.dependency_overrides[get_db_session] = fake_session
    allow_catalog_read_session(app)
    monkeypatch.setattr(router, "list_servers", list_servers)

    response = TestClient(app).get(
        "/api/v1/mcp/servers?fields=id,name,title,description,icons,latestVersion"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"] == {"count": 1, "nextCursor": ""}
    assert payload["servers"] == [
        {
            "id": str(server_id),
            "name": "io.github.example/weather",
            "title": "Weather",
            "description": "Weather tools",
            "icons": [{"src": "https://example.com/icon.png"}],
            "latestVersion": {
                "id": str(version_id),
                "version": "1.0.0",
                "status": "active",
                "qualityScore": None,
                "trustReport": None,
                "publishedAt": "2026-06-23T00:00:00+00:00",
                "publishedBy": None,
            },
        }
    ]
    assert "documentation" not in payload["servers"][0]
    assert "repository" not in payload["servers"][0]
    assert "partnerSupport" not in payload["servers"][0]


def test_list_servers_route_rejects_unknown_fields(monkeypatch) -> None:
    app = create_app()

    async def fake_session():
        class Session:
            pass

        yield Session()

    async def list_servers(*args, **kwargs):
        return RegistryServerListResponse(
            servers=[],
            metadata=RegistryListMetadata(count=0, nextCursor=""),
        )

    app.dependency_overrides[get_db_session] = fake_session
    allow_catalog_read_session(app)
    monkeypatch.setattr(router, "list_servers", list_servers)

    response = TestClient(app).get("/api/v1/mcp/servers?fields=id,unknown")

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid fields"


def test_search_servers_route_forwards_query_and_filters(monkeypatch) -> None:
    app = create_app()
    server_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_session():
        yield object()

    async def list_servers(*args, **kwargs):
        captured.update(kwargs)
        return RegistryServerListResponse(
            servers=[
                RegistryServerRead(
                    id=server_id,
                    name="io.github.example/weather",
                    title="Weather",
                    description="Weather tools",
                    documentation="",
                    websiteUrl="https://example.com",
                    repository={"url": "https://github.com/example/weather"},
                    icons=[],
                    status="active",
                    statusMessage="",
                    visibility="public",
                    latestVersion=None,
                    categories=[],
                    partnerSupport=[],
                    createdAt="2026-06-23T00:00:00Z",
                    updatedAt="2026-06-23T00:00:00Z",
                )
            ],
            metadata=RegistryListMetadata(count=1, nextCursor="5"),
        )

    app.dependency_overrides[get_db_session] = fake_session
    allow_catalog_read_session(app)
    monkeypatch.setattr(router, "list_servers", list_servers)

    response = TestClient(app).get(
        "/api/v1/mcp/servers/search"
        "?q=%20weather%20&limit=5&cursor=0&category=weather&partner=true"
        "&fields=name,title,description"
    )

    assert response.status_code == 200
    assert response.json() == {
        "servers": [
            {
                "name": "io.github.example/weather",
                "title": "Weather",
                "description": "Weather tools",
            }
        ],
        "metadata": {"count": 1, "nextCursor": "5"},
    }
    assert captured["search"] == "weather"
    assert captured["limit"] == 5
    assert captured["cursor"] == "0"
    assert captured["category"] == "weather"
    assert captured["partner"] is True


def test_search_servers_route_rejects_blank_query(monkeypatch) -> None:
    app = create_app()
    called = False

    async def fake_session():
        yield object()

    async def list_servers(*args, **kwargs):
        nonlocal called
        called = True
        return RegistryServerListResponse(
            servers=[],
            metadata=RegistryListMetadata(count=0, nextCursor=""),
        )

    app.dependency_overrides[get_db_session] = fake_session
    allow_catalog_read_session(app)
    monkeypatch.setattr(router, "list_servers", list_servers)

    response = TestClient(app).get("/api/v1/mcp/servers/search?q=%20%20")

    assert response.status_code == 400
    assert response.json()["detail"] == "search query required"
    assert called is False


def test_claim_ownership_requires_registry_write_scope_for_api_token(monkeypatch) -> None:
    app = create_app()
    called = False

    async def fake_session():
        yield object()

    async def claim(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("claim service should not be called")

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(dependencies, "authenticate_api_token", authenticate_low_scope_api_token)
    monkeypatch.setattr(router, "claim_server_ownership", claim)

    response = TestClient(app).post(
        "/api/v1/mcp/servers/io.github.example/weather/claim",
        headers=auth_headers(),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "API token missing required scope: registry:write"}
    assert called is False


def test_claim_ownership_accepts_registry_write_api_token(monkeypatch) -> None:
    app = create_app()
    server_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_session():
        class Session:
            async def commit(self) -> None:
                captured["committed"] = True

        yield Session()

    async def claim(*args, **kwargs):
        captured["args"] = args
        return RegistryOwnershipClaimResponse(
            server=RegistryServerRead(
                id=server_id,
                name="io.github.example/weather",
                title="Weather",
                description="Weather tools",
                documentation="# Large docs",
                websiteUrl="https://example.com",
                repository={"url": "https://github.com/example/weather"},
                icons=[],
                status="active",
                statusMessage="",
                visibility="public",
                latestVersion=None,
                categories=[],
                partnerSupport=[],
                createdAt="2026-06-23T00:00:00Z",
                updatedAt="2026-06-23T00:00:00Z",
            ),
            versions=[],
            verified=True,
            verificationSource="https://example.com/wardn.json",
        )

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(
        dependencies,
        "authenticate_api_token",
        authenticate_registry_write_user_api_token,
    )
    monkeypatch.setattr(router, "claim_server_ownership", claim)

    response = TestClient(app).post(
        "/api/v1/mcp/servers/io.github.example/weather/claim",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["verified"] is True
    assert captured["committed"] is True
    assert captured["args"][1] == "io.github.example/weather"


def test_quality_score_badge_renders_svg(monkeypatch) -> None:
    app = create_app()
    server_id = uuid4()
    version_id = uuid4()

    async def fake_session():
        yield object()

    async def get_server(*args, **kwargs):
        return RegistryServerDetailResponse(
            server=registry_detail_response(server_id, version_id).server,
            versions=[],
        )

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(router, "get_server_detail", get_server)

    response = TestClient(app).get("/api/v1/mcp/badges/quality/io.github.example/weather")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["cache-control"] == "public, max-age=300"
    assert "Wardn Score" in response.text
    assert "96/100" in response.text


def test_server_schema_tab_route_preserves_server_name(monkeypatch) -> None:
    app = create_app()
    server_id = uuid4()
    version_id = uuid4()
    captured: dict[str, str] = {}

    async def fake_session():
        yield object()

    async def get_schema_tab(_session, server_name):
        captured["server_name"] = server_name
        return {
            "server": {
                "id": str(server_id),
                "name": "io.github.example/weather",
                "title": "Weather",
                "description": "Weather tools",
                "websiteUrl": "https://example.com",
                "repository": {"url": "https://github.com/example/weather"},
                "icons": [],
                "categories": [],
                "updatedAt": "2026-06-23T00:00:00Z",
            },
            "versions": [
                {
                    "id": str(version_id),
                    "version": "1.0.0",
                    "title": "Weather",
                    "isLatest": True,
                    "packages": [{"registryType": "npm"}],
                    "remotes": [],
                    "serverJson": {"name": "io.github.example/weather"},
                }
            ],
        }

    app.dependency_overrides[get_db_session] = fake_session
    allow_catalog_read_session(app)
    monkeypatch.setattr(router, "get_server_schema_tab", get_schema_tab)

    response = TestClient(app).get(
        "/api/v1/mcp/servers/io.github.example/weather/tabs/schema"
    )

    assert response.status_code == 200
    assert captured["server_name"] == "io.github.example/weather"
    body = response.json()
    assert body["versions"][0]["serverJson"]["name"] == "io.github.example/weather"
    assert set(body["server"]) == {"id", "name", "title", "icons"}


def test_server_summary_route_returns_minimal_metadata(monkeypatch) -> None:
    app = create_app()
    server_id = uuid4()
    captured: dict[str, str] = {}

    async def fake_session():
        yield object()

    async def get_summary(_session, server_name):
        captured["server_name"] = server_name
        return {
            "id": str(server_id),
            "name": "io.github.example/weather",
            "title": "Weather",
            "description": "Weather tools",
            "icons": [{"src": "https://example.com/icon.png"}],
        }

    app.dependency_overrides[get_db_session] = fake_session
    allow_catalog_read_session(app)
    monkeypatch.setattr(router, "get_server_summary", get_summary)

    response = TestClient(app).get("/api/v1/mcp/servers/io.github.example/weather/summary")

    assert response.status_code == 200
    assert captured["server_name"] == "io.github.example/weather"
    assert set(response.json()) == {"id", "name", "title", "description", "icons"}


def test_quality_score_badge_supports_pending_score(monkeypatch) -> None:
    app = create_app()
    detail = registry_detail_response(uuid4(), uuid4())
    detail.server.quality_score = None

    async def fake_session():
        yield object()

    async def get_server(*args, **kwargs):
        return RegistryServerDetailResponse(server=detail.server, versions=[])

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(router, "get_server_detail", get_server)

    response = TestClient(app).get("/api/v1/mcp/badges/quality/io.github.example/weather")

    assert response.status_code == 200
    assert "pending" in response.text


def test_quality_score_badge_can_target_version(monkeypatch) -> None:
    app = create_app()
    detail = registry_detail_response(uuid4(), uuid4())
    detail.version.quality_score = 72

    async def fake_session():
        yield object()

    async def get_version(*args, **kwargs):
        return detail

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(router, "get_version_detail", get_version)

    response = TestClient(app).get(
        "/api/v1/mcp/badges/quality/io.github.example/weather?version=1.0.0"
    )

    assert response.status_code == 200
    assert "72/100" in response.text


def test_admin_create_maps_duplicate_to_conflict(monkeypatch) -> None:
    app = create_app()

    async def fake_session():
        class Session:
            async def commit(self) -> None:
                raise AssertionError("commit should not be called")

        yield Session()

    async def duplicate(*args, **kwargs):
        raise DuplicateRegistryVersionError("duplicate")

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(
        dependencies,
        "authenticate_api_token",
        authenticate_registry_admin_api_token,
    )
    monkeypatch.setattr(router, "create_server_version", duplicate)

    response = TestClient(app).post(
        "/api/v1/admin/mcp/servers",
        headers=auth_headers(),
        json={
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "io.github.example/weather",
            "title": "Weather",
            "description": "Weather tools for forecasts",
            "version": "1.0.0",
            "packages": [
                {
                    "registryType": "mcpb",
                    "identifier": "example.mcpb",
                    "version": "1.0.0",
                }
            ],
            "_meta": {"categories": ["weather"]},
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "server version already exists"}


def test_admin_create_requires_authentication() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/admin/mcp/servers",
        json={
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "io.github.example/weather",
            "description": "Weather tools for forecasts",
            "version": "1.0.0",
            "packages": [{"registryType": "mcpb", "identifier": "example.mcpb"}],
            "_meta": {"categories": ["weather"]},
        },
    )

    assert response.status_code == 401


def test_public_delete_server_allows_registry_write_user_token(monkeypatch) -> None:
    app = create_app()
    captured: dict[str, object] = {}

    async def fake_session():
        class Session:
            async def commit(self) -> None:
                captured["committed"] = True

        yield Session()

    async def delete(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(
        dependencies,
        "authenticate_api_token",
        authenticate_registry_write_user_api_token,
    )
    monkeypatch.setattr(router, "delete_server", delete)

    response = TestClient(app).delete(
        "/api/v1/mcp/servers/io.github.example/weather",
        headers=auth_headers(),
    )

    assert response.status_code == 204
    assert captured["committed"] is True
    assert captured["args"][1] == "io.github.example/weather"
    assert captured["kwargs"]["current_user"].is_superuser is False
    assert captured["kwargs"]["api_token"].scopes == ["registry:write"]
    assert captured["kwargs"]["actor_user_id"] == captured["kwargs"]["current_user"].id


def test_public_delete_server_requires_registry_write_scope(monkeypatch) -> None:
    app = create_app()

    async def fake_session():
        yield object()

    async def delete(*args, **kwargs):
        raise AssertionError("delete should not be called")

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(
        dependencies,
        "authenticate_api_token",
        authenticate_low_scope_api_token,
    )
    monkeypatch.setattr(router, "delete_server", delete)

    response = TestClient(app).delete(
        "/api/v1/mcp/servers/io.github.example/weather",
        headers=auth_headers(),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "API token missing required scope: registry:write"}


def test_admin_update_quality_score_uses_registry_score_scope(monkeypatch) -> None:
    app = create_app()
    captured: dict[str, object] = {}
    server_id = uuid4()
    version_id = uuid4()

    async def fake_session():
        class Session:
            async def commit(self) -> None:
                captured["committed"] = True

        yield Session()

    async def update_quality_score(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return registry_detail_response(server_id, version_id)

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(
        dependencies,
        "authenticate_api_token",
        authenticate_registry_score_api_token,
    )
    monkeypatch.setattr(router, "update_version_quality_score", update_quality_score)

    response = TestClient(app).patch(
        "/api/v1/admin/mcp/servers/io.github.example/weather/versions/1.0.0/quality-score",
        headers=auth_headers(),
        json={
            "qualityScore": 96,
            "trustReport": {
                "overallScore": 96,
                "scoreSource": "manual",
                "status": "passed",
                "summary": "Scorer report.",
                "components": [],
            },
        },
    )

    assert response.status_code == 200
    assert captured["committed"] is True
    assert captured["args"][1:] == ("io.github.example/weather", "1.0.0", 96)
    assert captured["kwargs"]["trust_report"].overall_score == 96


def test_admin_update_quality_score_requires_score_scope(monkeypatch) -> None:
    app = create_app()

    async def fake_session():
        yield object()

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(
        dependencies,
        "authenticate_api_token",
        authenticate_registry_admin_api_token,
    )

    response = TestClient(app).patch(
        "/api/v1/admin/mcp/servers/io.github.example/weather/versions/1.0.0/quality-score",
        headers=auth_headers(),
        json={"qualityScore": 96},
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "API token missing required scope: registry:score",
    }


def test_admin_update_quality_score_validates_score_range(monkeypatch) -> None:
    app = create_app()

    async def fake_session():
        yield object()

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(
        dependencies,
        "authenticate_api_token",
        authenticate_registry_score_api_token,
    )

    response = TestClient(app).patch(
        "/api/v1/admin/mcp/servers/io.github.example/weather/versions/1.0.0/quality-score",
        headers=auth_headers(),
        json={"qualityScore": 101},
    )

    assert response.status_code == 422


def test_category_create_maps_duplicate_to_conflict(monkeypatch) -> None:
    app = create_app()

    async def fake_session():
        class Session:
            async def commit(self) -> None:
                raise AssertionError("commit should not be called")

        yield Session()

    async def duplicate(*args, **kwargs):
        raise DuplicateRegistryCategoryError("duplicate")

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(
        dependencies,
        "authenticate_api_token",
        authenticate_registry_admin_api_token,
    )
    monkeypatch.setattr(router, "create_category", duplicate)

    response = TestClient(app).post(
        "/api/v1/mcp/categories",
        headers=auth_headers(),
        json={
            "slug": "automation",
            "name": "Automation",
            "description": "Workflow automation servers",
            "sortOrder": 120,
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "category slug already exists"}


def test_category_create_requires_authentication() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/mcp/categories",
        json={"slug": "automation", "name": "Automation"},
    )

    assert response.status_code == 401
