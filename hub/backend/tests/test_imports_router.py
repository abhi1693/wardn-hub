from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.imports import router
from app.modules.imports.schemas import ServerSourceImportResponse
from app.modules.users.dependencies import get_current_user


def test_import_server_source_requires_authentication() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/imports/server-source",
        json={"repositoryUrl": "https://github.com/acme/weather-mcp"},
    )

    assert response.status_code == 401


def test_import_server_source_returns_preview(monkeypatch) -> None:
    app = create_app()

    async def current_user():
        return SimpleNamespace(id=uuid4())

    def import_response(payload):
        return ServerSourceImportResponse(
            source="server.json",
            serverJson={
                "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
                "name": "io.github.acme/weather-mcp",
                "description": "Weather",
                "version": "1.0.0",
                "packages": [{"registryType": "npm", "identifier": "@acme/weather-mcp"}],
            },
            submissionPayload={
                "submissionType": "new_server",
                "serverJson": {
                    "name": "io.github.acme/weather-mcp",
                    "description": "Weather",
                    "version": "1.0.0",
                    "packages": [{"registryType": "npm", "identifier": "@acme/weather-mcp"}],
                },
            },
        )

    app.dependency_overrides[get_current_user] = current_user
    monkeypatch.setattr(router, "import_server_source", import_response)

    response = TestClient(app).post(
        "/api/v1/imports/server-source",
        json={"repositoryUrl": "https://github.com/acme/weather-mcp"},
    )

    assert response.status_code == 200
    assert response.json()["source"] == "server.json"
    assert response.json()["serverJson"]["name"] == "io.github.acme/weather-mcp"
