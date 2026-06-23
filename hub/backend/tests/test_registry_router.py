from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app
from app.modules.registry import router
from app.modules.registry.exceptions import DuplicateRegistryVersionError
from app.modules.users.dependencies import require_superuser


def test_registry_openapi_exposes_phase_one_paths() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()

    assert {
        "/api/v1/mcp/servers",
        "/api/v1/mcp/servers/{server_name}",
        "/api/v1/mcp/servers/{server_name}/versions",
        "/api/v1/mcp/servers/{server_name}/versions/{version}",
        "/api/v1/admin/mcp/servers",
        "/api/v1/admin/mcp/servers/{server_name}/versions/{version}",
        "/api/v1/admin/mcp/servers/{server_name}/versions/{version}/latest",
    }.issubset(set(schema["paths"]))
    assert schema["paths"]["/api/v1/mcp/servers"]["get"]["operationId"] == "mcp_servers_list"
    assert (
        schema["paths"]["/api/v1/admin/mcp/servers"]["post"]["operationId"]
        == "admin_mcp_servers_create_version"
    )


def test_admin_create_maps_duplicate_to_conflict(monkeypatch) -> None:
    app = create_app()

    async def fake_session():
        class Session:
            async def commit(self) -> None:
                raise AssertionError("commit should not be called")

        yield Session()

    async def duplicate(*args, **kwargs):
        raise DuplicateRegistryVersionError("duplicate")

    async def superuser():
        return object()

    app.dependency_overrides[get_db_session] = fake_session
    app.dependency_overrides[require_superuser] = superuser
    monkeypatch.setattr(router, "create_server_version", duplicate)

    response = TestClient(app).post(
        "/api/v1/admin/mcp/servers",
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
        },
    )

    assert response.status_code == 401
