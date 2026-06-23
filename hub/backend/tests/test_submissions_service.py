from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.registry.schemas import RegistryServerVersionCreate
from app.modules.submissions import service
from app.modules.submissions.exceptions import (
    InvalidSubmissionTransitionError,
    SubmissionValidationError,
)
from app.modules.submissions.schemas import SubmissionCreate, SubmissionUpdate
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = False
        self.refreshed: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushed = True

    async def refresh(self, instance: object) -> None:
        now = datetime(2026, 6, 23, tzinfo=UTC)
        if getattr(instance, "id", None) is None:
            instance.id = uuid4()
        if getattr(instance, "created_at", None) is None:
            instance.created_at = now
        if getattr(instance, "updated_at", None) is None:
            instance.updated_at = now
        if hasattr(instance, "rejection_message") and instance.rejection_message is None:
            instance.rejection_message = ""
        self.refreshed.append(instance)


def current_user(*, is_superuser: bool = False) -> User:
    return User(
        id=uuid4(),
        email=f"{uuid4()}@example.com",
        first_name="Test",
        last_name="User",
        is_active=True,
        is_superuser=is_superuser,
    )


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


def test_new_server_submission_starts_at_one_zero_zero() -> None:
    with pytest.raises(ValueError, match="new server submissions must start"):
        SubmissionCreate(serverJson=registry_payload(version="1.1.0"))


@pytest.mark.asyncio
async def test_new_version_submission_requires_published_server(monkeypatch) -> None:
    async def missing_server(*args, **kwargs):
        return None

    monkeypatch.setattr(service.registry_repository, "get_server", missing_server)

    with pytest.raises(SubmissionValidationError, match="published server"):
        await service.create_submission(
            FakeSession(),
            current_user(),
            SubmissionCreate(
                submissionType="new_version",
                serverJson=registry_payload(version="1.0.1"),
            ),
        )


@pytest.mark.asyncio
async def test_submission_lifecycle_publishes_approved_payload(monkeypatch) -> None:
    submitter = current_user()
    moderator = current_user(is_superuser=True)
    created_submission = None
    published_version_id = uuid4()

    async def no_published_version(*args, **kwargs):
        return None

    async def get_submission(*args, **kwargs):
        return created_submission

    async def publish_version(*args, **kwargs):
        return SimpleNamespace(version=SimpleNamespace(id=published_version_id))

    monkeypatch.setattr(service.registry_repository, "get_server_version", no_published_version)
    monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)
    monkeypatch.setattr(service.registry_service, "create_server_version", publish_version)

    response = await service.create_submission(
        FakeSession(),
        submitter,
        SubmissionCreate(serverJson=registry_payload()),
    )
    created_submission = service.repository.ServerSubmission(
        id=response.id,
        name=response.name,
        version=response.version,
        submitter_user_id=submitter.id,
        owner_user_id=submitter.id,
        owner_organization_id=None,
        submission_type=response.submission_type,
        status=response.status,
        server_json=response.server_json,
        validation_result=response.validation_result,
        rejection_message="",
        created_at=response.created_at,
        updated_at=response.updated_at,
    )

    submitted = await service.submit_submission(FakeSession(), submitter, response.id)
    assert submitted.status == "submitted"
    assert created_submission.submitted_at is not None

    approved = await service.approve_submission(FakeSession(), moderator, response.id)
    assert approved.status == "approved"
    assert approved.approver_user_id == moderator.id

    published = await service.publish_submission(FakeSession(), moderator, response.id)
    assert published.status == "published"
    assert published.published_server_version_id == published_version_id


@pytest.mark.asyncio
async def test_withdraw_requires_submitted_status(monkeypatch) -> None:
    submitter = current_user()
    submission = service.repository.ServerSubmission(
        id=uuid4(),
        name="io.github.example/weather",
        version="1.0.0",
        submitter_user_id=submitter.id,
        owner_user_id=submitter.id,
        owner_organization_id=None,
        submission_type="new_server",
        status="draft",
        server_json=registry_payload().model_dump(by_alias=True),
        validation_result={},
        rejection_message="",
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
        updated_at=datetime(2026, 6, 23, tzinfo=UTC),
    )

    async def get_submission(*args, **kwargs):
        return submission

    monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)

    with pytest.raises(InvalidSubmissionTransitionError):
        await service.withdraw_submission(FakeSession(), submitter, submission.id)


@pytest.mark.asyncio
async def test_update_submission_allowed_until_published(monkeypatch) -> None:
    submitter = current_user()
    submission = service.repository.ServerSubmission(
        id=uuid4(),
        name="io.github.example/weather",
        version="1.0.0",
        submitter_user_id=submitter.id,
        owner_user_id=submitter.id,
        owner_organization_id=None,
        submission_type="new_server",
        status="approved",
        server_json=registry_payload().model_dump(by_alias=True),
        validation_result={},
        rejection_message="",
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
        updated_at=datetime(2026, 6, 23, tzinfo=UTC),
    )

    async def get_submission(*args, **kwargs):
        return submission

    async def no_published_version(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)
    monkeypatch.setattr(service.registry_repository, "get_server_version", no_published_version)

    response = await service.update_submission(
        FakeSession(),
        submitter,
        submission.id,
        SubmissionUpdate(serverJson=registry_payload(version="1.0.1")),
    )

    assert response.status == "draft"
    assert response.version == "1.0.1"


@pytest.mark.asyncio
async def test_update_submission_rejects_published(monkeypatch) -> None:
    submitter = current_user()
    submission = service.repository.ServerSubmission(
        id=uuid4(),
        name="io.github.example/weather",
        version="1.0.0",
        submitter_user_id=submitter.id,
        owner_user_id=submitter.id,
        owner_organization_id=None,
        submission_type="new_server",
        status="published",
        server_json=registry_payload().model_dump(by_alias=True),
        validation_result={},
        rejection_message="",
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
        updated_at=datetime(2026, 6, 23, tzinfo=UTC),
    )

    async def get_submission(*args, **kwargs):
        return submission

    monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)

    with pytest.raises(InvalidSubmissionTransitionError, match="published submissions"):
        await service.update_submission(
            FakeSession(),
            submitter,
            submission.id,
            SubmissionUpdate(serverJson=registry_payload(version="1.0.1")),
        )
