from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.openapi import export_openapi


def test_openapi_exposes_phase_zero_paths() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["openapi"].startswith("3.")
    assert set(schema["paths"]) == {
        "/api/v1/health/live",
        "/api/v1/health/ready",
    }


def test_health_openapi_schema_is_specific() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()

    health_response = schema["paths"]["/api/v1/health/live"]["get"]["responses"]["200"]
    assert health_response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthStatus"
    }
    assert schema["components"]["schemas"]["HealthStatus"] == {
        "properties": {"status": {"type": "string", "title": "Status"}},
        "type": "object",
        "required": ["status"],
        "title": "HealthStatus",
    }


def test_export_openapi_writes_schema(tmp_path: Path) -> None:
    output_path = tmp_path / "openapi" / "wardn-hub-api.json"

    export_openapi(output_path)

    assert output_path.exists()
    assert "/api/v1/health/live" in output_path.read_text(encoding="utf-8")

