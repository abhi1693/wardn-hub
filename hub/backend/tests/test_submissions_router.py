from fastapi.testclient import TestClient

from app.main import create_app


def test_submissions_create_requires_authentication() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/submissions",
        json={
            "serverJson": {
                "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
                "name": "io.github.example/weather",
                "description": "Weather tools for forecasts",
                "version": "1.0.0",
                "packages": [{"registryType": "mcpb", "identifier": "example.mcpb"}],
            }
        },
    )

    assert response.status_code == 401


def test_audit_events_requires_authentication() -> None:
    response = TestClient(create_app()).get("/api/v1/audit/events")

    assert response.status_code == 401
