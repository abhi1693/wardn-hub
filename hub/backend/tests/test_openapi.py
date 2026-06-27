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
        "/api/v1/admin/mcp/servers",
        "/api/v1/admin/mcp/servers/{server_name}",
        "/api/v1/admin/mcp/servers/{server_name}/versions/{version}",
        "/api/v1/admin/mcp/servers/{server_name}/versions/{version}/latest",
        "/api/v1/audit/events",
        "/api/v1/auth/api-tokens",
        "/api/v1/auth/api-tokens/{token_id}",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/auth/providers",
        "/api/v1/auth/register",
        "/api/v1/events/deliveries",
        "/api/v1/events/deliveries/{delivery_id}",
        "/api/v1/events/deliveries/{delivery_id}/replay",
        "/api/v1/events/rules",
        "/api/v1/events/rules/{rule_id}",
        "/api/v1/events/rules/{rule_id}/rotate-secret",
        "/api/v1/events/rules/{rule_id}/test",
        "/api/v1/events/types",
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/imports/server-source",
        "/api/v1/mcp/catalog",
        "/api/v1/mcp/categories",
        "/api/v1/mcp/categories/{category_slug}",
        "/api/v1/mcp/servers",
        "/api/v1/mcp/servers/{server_name}",
        "/api/v1/mcp/servers/{server_name}/versions",
        "/api/v1/mcp/servers/{server_name}/versions/{version}",
        "/api/v1/organizations",
        "/api/v1/organizations/{organization_id}",
        "/api/v1/organizations/{organization_id}/memberships",
        "/api/v1/organizations/{organization_id}/memberships/{user_id}",
        "/api/v1/organizations/{organization_id}/roles",
        "/api/v1/partners",
        "/api/v1/partners/organizations/{organization_id}",
        "/api/v1/partners/organizations/{organization_id}/server-support",
        "/api/v1/partners/server-support/{support_id}",
        "/api/v1/submissions",
        "/api/v1/submissions/{submission_id}",
        "/api/v1/submissions/{submission_id}/approve",
        "/api/v1/submissions/{submission_id}/publish",
        "/api/v1/submissions/{submission_id}/reject",
        "/api/v1/submissions/{submission_id}/submit",
        "/api/v1/submissions/{submission_id}/withdraw",
        "/api/v1/users",
        "/api/v1/users/{user_id}",
        "/api/v1/users/bootstrap",
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


def test_submission_openapi_has_typed_import_examples() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()
    schemas = schema["components"]["schemas"]

    assert schemas["ServerSourceImportRequest"]["examples"][0]["repositoryUrl"].startswith(
        "https://github.com/"
    )
    assert schemas["ServerSourceImportResponse"]["properties"]["packages"]["items"] == {
        "$ref": "#/components/schemas/RegistryPackage"
    }
    assert schemas["ServerSourceImportResponse"]["properties"]["remotes"]["items"] == {
        "$ref": "#/components/schemas/RegistryRemote"
    }
    assert schemas["ServerSourceImportResponse"]["properties"]["serverJson"] == {
        "$ref": "#/components/schemas/ServerSourceImportServerJson"
    }
    assert schemas["SubmissionCreate"]["examples"][0]["serverJson"]["packages"][0][
        "registryType"
    ] == "npm"


def test_export_openapi_writes_schema(tmp_path: Path) -> None:
    output_path = tmp_path / "openapi" / "wardn-hub-api.json"

    export_openapi(output_path)

    assert output_path.exists()
    assert "/api/v1/health/live" in output_path.read_text(encoding="utf-8")
