from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app
from app.modules.submissions import router as submissions_router
from app.modules.submissions.exceptions import SubmissionNotFoundError, SubmissionValidationError
from app.modules.submissions.schemas import (
    SubmissionListMetadata,
    SubmissionListResponse,
    SubmissionStatusCounts,
)
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


def test_create_and_submit_submission_returns_created(monkeypatch) -> None:
    app = create_app()
    captured: dict[str, object] = {}

    class FakeSession:
        async def commit(self) -> None:
            captured["committed"] = True

    async def fake_session():
        yield FakeSession()

    async def authenticate_api_token(*args, **kwargs):
        return (
            User(id=uuid4(), email="submitter@example.com"),
            SimpleNamespace(id=uuid4(), scopes=["submissions:write"], organization_ids=[]),
        )

    async def submit_submission_record(*args, **kwargs):
        captured.update(kwargs)
        now = datetime(2026, 6, 30, tzinfo=UTC)
        submission_id = uuid4()
        user_id = uuid4()
        return {
            "id": str(submission_id),
            "name": "io.github.example/weather",
            "version": "1.0.0",
            "submitterUserId": str(user_id),
            "ownerUserId": str(user_id),
            "ownerOrganizationId": None,
            "submissionType": "new_server",
            "status": "submitted",
            "serverJson": {
                "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
                "name": "io.github.example/weather",
                "description": "Weather tools for forecasts",
                "version": "1.0.0",
                "packages": [{"registryType": "mcpb", "identifier": "example.mcpb"}],
                "_meta": {"categories": ["weather"]},
            },
            "validationResult": {"status": "passed", "checks": []},
            "submittedAt": now.isoformat(),
            "approvedAt": None,
            "approverUserId": None,
            "rejectionMessage": "",
            "publishedServerVersionId": None,
            "createdAt": now.isoformat(),
            "updatedAt": now.isoformat(),
        }

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(dependencies, "authenticate_api_token", authenticate_api_token)
    monkeypatch.setattr(
        submissions_router,
        "submit_submission_request",
        submit_submission_record,
    )

    response = TestClient(app).post(
        "/api/v1/submissions/submit",
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

    assert response.status_code == 201
    assert response.json()["status"] == "submitted"
    assert captured["committed"] is True


def test_submit_missing_submission_returns_not_found(monkeypatch) -> None:
    app = create_app()

    async def fake_session():
        yield object()

    async def authenticate_api_token(*args, **kwargs):
        return (
            User(id=uuid4(), email="submitter@example.com"),
            SimpleNamespace(id=uuid4(), scopes=["submissions:write"], organization_ids=[]),
        )

    async def submit_submission_record(*args, **kwargs):
        raise SubmissionNotFoundError("submission not found")

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(dependencies, "authenticate_api_token", authenticate_api_token)
    monkeypatch.setattr(
        submissions_router,
        "submit_submission_request",
        submit_submission_record,
    )

    response = TestClient(app).post(
        "/api/v1/submissions/submit",
        headers={"Authorization": "Bearer wardn_hub_key.secret"},
        json={"submissionId": str(uuid4())},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "submission not found"}


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


def test_submissions_list_passes_pagination_filters(monkeypatch) -> None:
    app = create_app()
    captured: dict[str, object] = {}

    async def fake_session():
        yield object()

    async def authenticate_api_token(*args, **kwargs):
        return (
            User(id=uuid4(), email="moderator@example.com", is_global_moderator=True),
            SimpleNamespace(id=uuid4(), scopes=["submissions:read"], organization_ids=[]),
        )

    async def list_submission_records(*args, **kwargs):
        captured.update(kwargs)
        return SubmissionListResponse(
            submissions=[],
            metadata=SubmissionListMetadata(page=2, perPage=10, total=0, pages=0, count=0),
            statusCounts=SubmissionStatusCounts(),
        )

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(dependencies, "authenticate_api_token", authenticate_api_token)
    monkeypatch.setattr(submissions_router, "list_submissions", list_submission_records)

    response = TestClient(app).get(
        "/api/v1/submissions?page=2&perPage=10&status=submitted&ownerScope=all",
        headers={"Authorization": "Bearer wardn_hub_key.secret"},
    )

    assert response.status_code == 200
    assert response.json()["metadata"] == {
        "page": 2,
        "perPage": 10,
        "total": 0,
        "pages": 0,
        "count": 0,
    }
    assert captured["page"] == 2
    assert captured["per_page"] == 10
    assert captured["status"] == "submitted"
    assert captured["owner_scope"] == "all"


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
