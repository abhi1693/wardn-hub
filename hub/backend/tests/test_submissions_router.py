from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app
from app.modules.submissions import router as submissions_router
from app.modules.submissions.exceptions import SubmissionValidationError
from app.modules.users import dependencies
from app.modules.users.models import User


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
                "_meta": {"categories": ["weather"]},
            }
        },
    )

    assert response.status_code == 401


def test_audit_events_requires_authentication() -> None:
    response = TestClient(create_app()).get("/api/v1/audit/events")

    assert response.status_code == 401


def test_submission_write_rejects_token_without_write_scope(monkeypatch) -> None:
    app = create_app()

    async def fake_session():
        yield object()

    async def authenticate_api_token(*args, **kwargs):
        return (
            SimpleNamespace(id=uuid4(), is_active=True),
            SimpleNamespace(scopes=["catalog:read", "submissions:read"]),
        )

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(dependencies, "authenticate_api_token", authenticate_api_token)

    response = TestClient(app).post(
        "/api/v1/submissions",
        headers={"Authorization": "Bearer wardn_hub_key.secret"},
        json={
            "serverJson": {
                "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
                "name": "io.github.example/weather",
                "description": "Weather tools for forecasts",
                "version": "1.0.0",
                "packages": [{"registryType": "mcpb", "identifier": "example.mcpb"}],
                "_meta": {"categories": ["weather"]},
            }
        },
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "API token missing required scope: submissions:write",
    }


def test_submission_delete_rejects_token_without_write_scope(monkeypatch) -> None:
    app = create_app()

    async def fake_session():
        yield object()

    async def authenticate_api_token(*args, **kwargs):
        return (
            SimpleNamespace(id=uuid4(), is_active=True),
            SimpleNamespace(scopes=["catalog:read", "submissions:read"]),
        )

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(dependencies, "authenticate_api_token", authenticate_api_token)

    response = TestClient(app).delete(
        f"/api/v1/submissions/{uuid4()}",
        headers={"Authorization": "Bearer wardn_hub_key.secret"},
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "API token missing required scope: submissions:write",
    }


def test_publish_submission_validation_error_returns_bad_request(monkeypatch) -> None:
    app = create_app()

    async def fake_session():
        yield object()

    async def authenticate_api_token(*args, **kwargs):
        return (
            User(id=uuid4(), email="moderator@example.com", is_superuser=True),
            SimpleNamespace(id=uuid4(), scopes=["submissions:publish"], organization_ids=[]),
        )

    async def publish(*args, **kwargs):
        raise SubmissionValidationError("at least one category is required")

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(dependencies, "authenticate_api_token", authenticate_api_token)
    monkeypatch.setattr(submissions_router, "publish_submission", publish)

    response = TestClient(app).post(
        f"/api/v1/submissions/{uuid4()}/publish",
        headers={"Authorization": "Bearer wardn_hub_key.secret"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "at least one category is required"}
