from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.events.models import EventRecord
from app.modules.organizations.exceptions import OrganizationAccessDeniedError
from app.modules.registry.models import RegistryServer
from app.modules.registry.schemas import RegistryEnvironmentVariable, RegistryServerVersionCreate
from app.modules.submissions import service
from app.modules.submissions.exceptions import (
    InvalidSubmissionTransitionError,
    SubmissionAccessDeniedError,
    SubmissionValidationError,
)
from app.modules.submissions.schemas import SubmissionCreate, SubmissionUpdate
from app.modules.users.models import User, UserAPIToken


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.flushed = False
        self.refreshed: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def execute(self, *args, **kwargs):
        return SimpleNamespace(
            scalar_one_or_none=lambda: None,
            scalars=lambda: SimpleNamespace(all=lambda: []),
        )

    async def delete(self, instance: object) -> None:
        self.deleted.append(instance)

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


def current_user(*, is_superuser: bool = False, is_global_moderator: bool = False) -> User:
    return User(
        id=uuid4(),
        email=f"{uuid4()}@example.com",
        first_name="Test",
        last_name="User",
        is_active=True,
        is_superuser=is_superuser,
        is_global_moderator=is_global_moderator,
    )


def restricted_api_token(*organization_ids) -> UserAPIToken:
    return UserAPIToken(
        organization_ids=[str(organization_id) for organization_id in organization_ids],
        scopes=["submissions:read", "submissions:write"],
    )


def submission_record(
    *,
    submitter_user_id,
    owner_user_id=None,
    owner_organization_id=None,
    status: str = "draft",
):
    now = datetime(2026, 6, 23, tzinfo=UTC)
    return service.repository.ServerSubmission(
        id=uuid4(),
        name="io.github.example/weather",
        version="1.0.0",
        submitter_user_id=submitter_user_id,
        owner_user_id=owner_user_id,
        owner_organization_id=owner_organization_id,
        submission_type="new_server",
        status=status,
        server_json=complete_registry_payload().model_dump(by_alias=True),
        validation_result={},
        rejection_message="",
        created_at=now,
        updated_at=now,
    )


def registry_server(
    *,
    owner_user_id=None,
    owner_organization_id=None,
    status: str = "active",
) -> RegistryServer:
    now = datetime(2026, 6, 23, tzinfo=UTC)
    return RegistryServer(
        id=uuid4(),
        name="io.github.example/weather",
        owner_user_id=owner_user_id,
        owner_organization_id=owner_organization_id,
        title="Weather",
        description="Weather tools for forecasts",
        documentation="# Weather MCP",
        website_url="https://example.com/weather",
        repository=None,
        icons=[],
        status=status,
        status_message="",
        visibility="public",
        created_at=now,
        updated_at=now,
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
            "_meta": {"categories": ["weather"]},
        }
    )


def complete_registry_payload(version: str = "1.0.0") -> RegistryServerVersionCreate:
    return RegistryServerVersionCreate(
        **{
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "io.github.example/weather",
            "title": "Weather",
            "description": "Weather tools for forecasts",
            "documentation": (
                "## Installation\nUse `npx -y @example/weather-mcp` in an MCP client.\n\n"
                "## Configuration\nNo environment variables are required.\n\n"
                "## Capabilities\nProvides weather tools.\n\n"
                "## Limitations\nForecast availability depends on the upstream service."
            ),
            "version": version,
            "packages": [
                {
                    "registryType": "npm",
                    "identifier": "@example/weather-mcp",
                    "version": version,
                    "transport": {
                        "type": "stdio",
                        "command": "npx",
                        "args": ["-y", "@example/weather-mcp"],
                    },
                }
            ],
            "_meta": {
                "categories": ["weather"],
                "sourceReview": {
                    "filesRead": ["README.md"],
                    "clientConfigSnippetsFound": True,
                    "installCommands": ["npx -y @example/weather-mcp"],
                    "commandArguments": ["-y", "@example/weather-mcp"],
                    "environmentVariables": [],
                    "prerequisites": [],
                    "capabilitiesReviewed": True,
                    "limitationsReviewed": True,
                    "unknowns": [],
                }
            },
        }
    )


def test_new_server_submission_starts_at_one_zero_zero() -> None:
    with pytest.raises(ValueError, match="new server submissions must start"):
        SubmissionCreate(serverJson=registry_payload(version="1.1.0"))


def test_validation_warns_when_source_review_and_transport_details_are_missing() -> None:
    result = service.validation_result_for(registry_payload())

    assert result["status"] == "warning"
    assert {
        check["name"]
        for check in result["checks"]
        if check["status"] == "warning"
    } >= {"packageTransportDetails", "documentation", "sourceReview"}


def test_validation_passes_with_source_review_and_transport_details() -> None:
    assert service.validation_result_for(complete_registry_payload())["status"] == "passed"


def test_validation_passes_with_llm_source_review_channel() -> None:
    payload = complete_registry_payload()
    assert payload.meta is not None
    source_review = payload.meta["sourceReview"]
    assert isinstance(source_review, dict)
    payload.meta["sourceReview"] = {"llm": source_review}

    result = service.validation_result_for(payload)

    assert result["status"] == "passed"
    assert any(
        check["name"] == "sourceReview"
        and check["status"] == "passed"
        and "(llm)" in check["message"]
        for check in result["checks"]
    )


def test_validation_does_not_mix_human_and_llm_source_review_channels() -> None:
    payload = complete_registry_payload()
    assert payload.meta is not None
    payload.meta["sourceReview"] = {
        "human": {
            "filesRead": ["README.md"],
            "installCommands": ["npx -y @example/weather-mcp"],
        },
        "llm": {
            "commandArguments": ["-y"],
            "capabilitiesReviewed": True,
            "limitationsReviewed": True,
            "unknowns": [],
        },
    }

    result = service.validation_result_for(payload)

    assert result["status"] == "warning"
    assert any(
        check["name"] == "sourceReview"
        and "human:" in check["message"]
        and "llm:" in check["message"]
        for check in result["checks"]
    )


@pytest.mark.parametrize(
    ("registry_type", "identifier"),
    [
        ("npm", "@ankimcp/anki-mcp-server:0.21.0"),
        ("npm", "@ankimcp/anki-mcp-server@0.21.0"),
        ("uvx", "anki-mcp-server==0.21.0"),
        ("docker", "ghcr.io/ankimcp/anki-mcp-server:0.21.0"),
        ("oci", "registry.example.com:5000/ankimcp/server:0.21.0"),
    ],
)
def test_validation_rejects_package_identifier_embedded_version(
    registry_type: str,
    identifier: str,
) -> None:
    payload = complete_registry_payload()
    payload.packages[0].registry_type = registry_type
    payload.packages[0].identifier = identifier

    result = service.validation_result_for(payload)

    assert result["status"] == "failed"
    assert any(
        check["name"] == "packages" and "must not include a version" in check["message"]
        for check in result["checks"]
    )


def test_validation_allows_docker_registry_port_without_tag() -> None:
    payload = complete_registry_payload()
    payload.packages[0].registry_type = "docker"
    payload.packages[0].identifier = "registry.example.com:5000/ankimcp/server"

    assert service.validation_result_for(payload)["status"] == "passed"


def test_validation_rejects_env_placeholder_values() -> None:
    payload = complete_registry_payload()
    package = payload.packages[0]
    assert package.transport is not None
    package.transport.env = {"WEATHER_API_KEY": "${WEATHER_API_KEY}"}

    result = service.validation_result_for(payload)

    assert result["status"] == "failed"
    assert any(
        check["name"] == "envPlaceholders" and check["status"] == "failed"
        for check in result["checks"]
    )


def test_validation_rejects_source_review_placeholder_values() -> None:
    payload = complete_registry_payload()
    assert payload.meta is not None
    source_review = payload.meta["sourceReview"]
    assert isinstance(source_review, dict)
    source_review["environmentVariables"] = [
        {
            "name": "WEATHER_API_KEY",
            "default": "${WEATHER_API_KEY}",
            "secret": True,
        }
    ]

    result = service.validation_result_for(payload)

    assert result["status"] == "failed"
    assert any(
        check["name"] == "envPlaceholders" and check["status"] == "failed"
        for check in result["checks"]
    )


def test_validation_rejects_duplicate_environment_variables() -> None:
    payload = complete_registry_payload()
    package = payload.packages[0]
    package.environmentVariables = [
        {"name": "DEBUG", "description": "Enable debug logging."},
        {"name": "DEBUG", "description": "Duplicate debug setting."},
    ]
    assert payload.meta is not None
    source_review = payload.meta["sourceReview"]
    assert isinstance(source_review, dict)
    source_review["environmentVariables"] = [
        {"name": "CI", "description": "Disable usage statistics in CI."},
        {"name": "CI", "description": "Duplicate CI setting."},
    ]

    result = service.validation_result_for(payload)

    assert result["status"] == "failed"
    assert any(
        check["name"] == "duplicateEnvironmentVariables"
        and "DEBUG" in check["message"]
        and "CI" in check["message"]
        for check in result["checks"]
    )


def test_validation_reads_official_snake_case_package_environment_variables() -> None:
    raw_payload = registry_payload().model_dump(by_alias=True)
    raw_payload["packages"] = [
        {
            "registry_type": "npm",
            "identifier": "@example/weather-mcp",
            "transport": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@example/weather-mcp"],
            },
            "environment_variables": [
                {
                    "name": "WEATHER_API_KEY",
                    "description": "Weather API key.",
                    "is_required": True,
                    "is_secret": True,
                    "format": "string",
                },
                {
                    "name": "WEATHER_API_KEY",
                    "description": "Duplicate weather API key.",
                    "is_required": True,
                    "is_secret": True,
                    "format": "string",
                },
            ],
        }
    ]
    payload = RegistryServerVersionCreate(
        **raw_payload
    )

    result = service.validation_result_for(payload)

    assert result["status"] == "failed"
    assert any(
        check["name"] == "duplicateEnvironmentVariables"
        and "@example/weather-mcp: WEATHER_API_KEY" in check["message"]
        for check in result["checks"]
    )


def test_validation_warns_when_transport_env_lacks_typed_metadata() -> None:
    payload = complete_registry_payload()
    package = payload.packages[0]
    assert package.transport is not None
    package.transport.env = {
        "WEATHER_API_KEY": "",
        "WEATHER_TIMEOUT": "5000",
    }
    package.environment_variables = [
        RegistryEnvironmentVariable(
            name="WEATHER_API_KEY",
            description="Weather API key.",
            is_required=True,
            is_secret=True,
            format="string",
        )
    ]

    result = service.validation_result_for(payload)

    assert result["status"] == "warning"
    assert any(
        check["name"] == "environmentMetadata"
        and "WEATHER_TIMEOUT" in check["message"]
        and "WEATHER_API_KEY" not in check["message"]
        for check in result["checks"]
    )


def test_validation_rejects_unreadable_source_review_entries() -> None:
    payload = complete_registry_payload()
    assert payload.meta is not None
    source_review = payload.meta["sourceReview"]
    assert isinstance(source_review, dict)
    source_review["commandArguments"] = [
        {"choices": ["--stdio", "--help"]},
        {"nested": {"value": "--verbose"}},
    ]

    result = service.validation_result_for(payload)

    assert result["status"] == "failed"
    assert any(
        check["name"] == "sourceReviewFormat"
        and "commandArguments" in check["message"]
        for check in result["checks"]
    )


def test_validation_rejects_unreadable_llm_source_review_entries() -> None:
    payload = complete_registry_payload()
    assert payload.meta is not None
    source_review = payload.meta["sourceReview"]
    assert isinstance(source_review, dict)
    source_review["commandArguments"] = [{"nested": {"value": "--verbose"}}]
    payload.meta["sourceReview"] = {"llm": source_review}

    result = service.validation_result_for(payload)

    assert result["status"] == "failed"
    assert any(
        check["name"] == "sourceReviewFormat"
        and "llm.commandArguments" in check["message"]
        for check in result["checks"]
    )


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
async def test_new_server_submission_rejects_existing_server_name(monkeypatch) -> None:
    async def existing_server(*args, **kwargs):
        return registry_server(owner_user_id=uuid4())

    monkeypatch.setattr(service.registry_repository, "get_server", existing_server)

    with pytest.raises(SubmissionValidationError, match="server already exists"):
        await service.create_submission(
            FakeSession(),
            current_user(),
            SubmissionCreate(serverJson=complete_registry_payload()),
        )


@pytest.mark.asyncio
async def test_new_version_submission_rejects_non_owner_personal_server(monkeypatch) -> None:
    existing_owner_id = uuid4()

    async def existing_server(*args, **kwargs):
        return registry_server(owner_user_id=existing_owner_id)

    monkeypatch.setattr(service.registry_repository, "get_server", existing_server)

    with pytest.raises(SubmissionAccessDeniedError, match="server owner"):
        await service.create_submission(
            FakeSession(),
            current_user(),
            SubmissionCreate(
                submissionType="new_version",
                serverJson=complete_registry_payload(version="1.0.1"),
            ),
        )


@pytest.mark.asyncio
async def test_new_version_submission_allows_personal_server_owner(monkeypatch) -> None:
    owner = current_user()

    async def existing_server(*args, **kwargs):
        return registry_server(owner_user_id=owner.id)

    monkeypatch.setattr(service.registry_repository, "get_server", existing_server)

    response = await service.create_submission(
        FakeSession(),
        owner,
        SubmissionCreate(
            submissionType="new_version",
            serverJson=complete_registry_payload(version="1.0.1"),
        ),
    )

    assert response.submission_type == "new_version"
    assert response.owner_user_id == owner.id


@pytest.mark.asyncio
async def test_new_version_submission_requires_existing_owner_organization(monkeypatch) -> None:
    existing_organization_id = uuid4()

    async def existing_server(*args, **kwargs):
        return registry_server(owner_organization_id=existing_organization_id)

    async def allow_permission(*args, **kwargs):
        return None

    monkeypatch.setattr(service.registry_repository, "get_server", existing_server)
    monkeypatch.setattr(service, "require_organization_permission", allow_permission)

    with pytest.raises(SubmissionAccessDeniedError, match="server owner organization"):
        await service.create_submission(
            FakeSession(),
            current_user(),
            SubmissionCreate(
                ownerOrganizationId=uuid4(),
                submissionType="new_version",
                serverJson=complete_registry_payload(version="1.0.1"),
            ),
        )


@pytest.mark.asyncio
async def test_new_version_submission_requires_update_permission_for_owner_organization(
    monkeypatch,
) -> None:
    organization_id = uuid4()

    async def existing_server(*args, **kwargs):
        return registry_server(owner_organization_id=organization_id)

    async def deny_update_permission(*args, **kwargs):
        raise OrganizationAccessDeniedError("servers.update permission required")

    monkeypatch.setattr(service.registry_repository, "get_server", existing_server)
    monkeypatch.setattr(service, "require_organization_permission", deny_update_permission)

    with pytest.raises(SubmissionAccessDeniedError, match="owner organization"):
        await service.create_submission(
            FakeSession(),
            current_user(),
            SubmissionCreate(
                ownerOrganizationId=organization_id,
                submissionType="new_version",
                serverJson=complete_registry_payload(version="1.0.1"),
            ),
        )


@pytest.mark.asyncio
async def test_create_submission_rejects_invalid_remote_target() -> None:
    invalid_payload = RegistryServerVersionCreate(
        **{
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "io.github.example/weather",
            "title": "Weather",
            "description": "Weather tools for forecasts",
            "version": "1.0.0",
            "remotes": [{"type": "streamable-http", "url": "ftp://example.com/mcp"}],
            "_meta": {"categories": ["weather"]},
        }
    )

    with pytest.raises(SubmissionValidationError, match="Remote target URL"):
        await service.create_submission(
            FakeSession(),
            current_user(),
            SubmissionCreate(serverJson=invalid_payload),
        )


@pytest.mark.asyncio
async def test_create_submission_requires_organization_publish_permission(monkeypatch) -> None:
    async def deny_permission(*args, **kwargs):
        raise OrganizationAccessDeniedError("permission denied")

    monkeypatch.setattr(service, "require_organization_permission", deny_permission)

    with pytest.raises(SubmissionAccessDeniedError, match="owner organization"):
        await service.create_submission(
            FakeSession(),
            current_user(),
            SubmissionCreate(
                ownerOrganizationId=uuid4(),
                serverJson=registry_payload(),
            ),
        )


@pytest.mark.asyncio
async def test_create_submission_rejects_api_token_outside_organization_allowlist(
    monkeypatch,
) -> None:
    allowed_organization_id = uuid4()
    denied_organization_id = uuid4()

    async def allow_permission(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "require_organization_permission", allow_permission)

    with pytest.raises(SubmissionAccessDeniedError, match="API token organization"):
        await service.create_submission(
            FakeSession(),
            current_user(),
            SubmissionCreate(
                ownerOrganizationId=denied_organization_id,
                serverJson=registry_payload(),
            ),
            api_token=restricted_api_token(allowed_organization_id),
        )


@pytest.mark.asyncio
async def test_create_submission_rejects_restricted_api_token_personal_owner() -> None:
    with pytest.raises(SubmissionAccessDeniedError, match="API token organization"):
        await service.create_submission(
            FakeSession(),
            current_user(),
            SubmissionCreate(serverJson=registry_payload()),
            api_token=restricted_api_token(uuid4()),
        )


@pytest.mark.asyncio
async def test_restricted_api_token_filters_listed_submissions(monkeypatch) -> None:
    user = current_user(is_global_moderator=True)
    allowed_organization_id = uuid4()
    denied_organization_id = uuid4()
    allowed_submission = submission_record(
        submitter_user_id=uuid4(),
        owner_organization_id=allowed_organization_id,
    )
    denied_submission = submission_record(
        submitter_user_id=uuid4(),
        owner_organization_id=denied_organization_id,
    )
    personal_submission = submission_record(
        submitter_user_id=user.id,
        owner_user_id=user.id,
        owner_organization_id=None,
    )

    async def list_submission_records(*args, **kwargs):
        return [allowed_submission, denied_submission, personal_submission]

    monkeypatch.setattr(service.repository, "list_submissions", list_submission_records)

    response = await service.list_submissions(
        FakeSession(),
        user,
        api_token=restricted_api_token(allowed_organization_id),
    )

    assert [submission.id for submission in response.submissions] == [allowed_submission.id]


@pytest.mark.asyncio
async def test_restricted_api_token_cannot_read_submission_outside_allowlist(
    monkeypatch,
) -> None:
    user = current_user(is_global_moderator=True)
    submission = submission_record(
        submitter_user_id=uuid4(),
        owner_organization_id=uuid4(),
        status="submitted",
    )

    async def get_submission(*args, **kwargs):
        return submission

    monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)

    with pytest.raises(SubmissionAccessDeniedError, match="API token organization"):
        await service.get_submission(
            FakeSession(),
            user,
            submission.id,
            api_token=restricted_api_token(uuid4()),
        )


@pytest.mark.asyncio
async def test_global_moderator_lists_all_submissions(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def list_submission_records(*args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(service.repository, "list_submissions", list_submission_records)

    response = await service.list_submissions(
        FakeSession(),
        current_user(is_global_moderator=True),
    )

    assert response.submissions == []
    assert captured["include_all"] is True


@pytest.mark.asyncio
async def test_global_moderator_can_read_any_submission(monkeypatch) -> None:
    moderator = current_user(is_global_moderator=True)
    submission = service.repository.ServerSubmission(
        id=uuid4(),
        name="io.github.example/weather",
        version="1.0.0",
        submitter_user_id=uuid4(),
        owner_user_id=uuid4(),
        owner_organization_id=None,
        submission_type="new_server",
        status="submitted",
        server_json=complete_registry_payload().model_dump(by_alias=True),
        validation_result={},
        rejection_message="",
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
        updated_at=datetime(2026, 6, 23, tzinfo=UTC),
    )

    async def get_submission(*args, **kwargs):
        return submission

    monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)

    response = await service.get_submission(FakeSession(), moderator, submission.id)

    assert response.id == submission.id


@pytest.mark.asyncio
async def test_organization_member_can_read_organization_submission(monkeypatch) -> None:
    user = current_user()
    organization_id = uuid4()
    submission = submission_record(
        submitter_user_id=uuid4(),
        owner_organization_id=organization_id,
        status="submitted",
    )

    async def get_submission(*args, **kwargs):
        return submission

    async def get_membership(*args, **kwargs):
        return object()

    monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)
    monkeypatch.setattr(
        service.organization_repository,
        "get_organization_membership",
        get_membership,
    )

    response = await service.get_submission(FakeSession(), user, submission.id)

    assert response.id == submission.id


@pytest.mark.asyncio
async def test_non_member_cannot_read_organization_submission(monkeypatch) -> None:
    user = current_user()
    submission = submission_record(
        submitter_user_id=uuid4(),
        owner_organization_id=uuid4(),
        status="submitted",
    )

    async def get_submission(*args, **kwargs):
        return submission

    async def get_membership(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)
    monkeypatch.setattr(
        service.organization_repository,
        "get_organization_membership",
        get_membership,
    )

    with pytest.raises(SubmissionAccessDeniedError, match="submission access denied"):
        await service.get_submission(FakeSession(), user, submission.id)


@pytest.mark.asyncio
async def test_global_moderator_cannot_submit_other_user_draft(monkeypatch) -> None:
    moderator = current_user(is_global_moderator=True)
    submission = service.repository.ServerSubmission(
        id=uuid4(),
        name="io.github.example/weather",
        version="1.0.0",
        submitter_user_id=uuid4(),
        owner_user_id=uuid4(),
        owner_organization_id=None,
        submission_type="new_server",
        status="draft",
        server_json=complete_registry_payload().model_dump(by_alias=True),
        validation_result={},
        rejection_message="",
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
        updated_at=datetime(2026, 6, 23, tzinfo=UTC),
    )

    async def get_submission(*args, **kwargs):
        return submission

    monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)

    with pytest.raises(SubmissionAccessDeniedError):
        await service.submit_submission(FakeSession(), moderator, submission.id)


@pytest.mark.asyncio
async def test_submission_lifecycle_publishes_approved_payload(monkeypatch) -> None:
    submitter = current_user()
    moderator = current_user(is_superuser=True)
    created_submission = None
    published_version_id = uuid4()
    publish_kwargs = {}

    async def no_published_version(*args, **kwargs):
        return None

    async def get_submission(*args, **kwargs):
        return created_submission

    async def publish_version(*args, **kwargs):
        publish_kwargs.update(kwargs)
        return SimpleNamespace(version=SimpleNamespace(id=published_version_id))

    monkeypatch.setattr(service.registry_repository, "get_server_version", no_published_version)
    monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)
    monkeypatch.setattr(service.registry_service, "create_server_version", publish_version)

    response = await service.create_submission(
        FakeSession(),
        submitter,
        SubmissionCreate(serverJson=complete_registry_payload()),
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
    assert publish_kwargs == {
        "owner_user_id": submitter.id,
        "owner_organization_id": None,
        "created_by_user_id": submitter.id,
        "updated_by_user_id": moderator.id,
        "publisher_user_id": moderator.id,
    }


@pytest.mark.asyncio
async def test_publish_submission_rejects_stale_new_server_for_existing_name(monkeypatch) -> None:
    submitter = current_user()
    moderator = current_user(is_superuser=True)
    submission = submission_record(
        submitter_user_id=submitter.id,
        owner_user_id=submitter.id,
        status="approved",
    )

    async def get_submission(*args, **kwargs):
        return submission

    async def existing_server(*args, **kwargs):
        return registry_server(owner_user_id=uuid4())

    async def publish_version(*args, **kwargs):
        raise AssertionError("publish should not be called")

    monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)
    monkeypatch.setattr(service.registry_repository, "get_server", existing_server)
    monkeypatch.setattr(service.registry_service, "create_server_version", publish_version)

    with pytest.raises(SubmissionValidationError, match="server already exists"):
        await service.publish_submission(FakeSession(), moderator, submission.id)


@pytest.mark.asyncio
async def test_publish_submission_rejects_stale_payload_missing_categories(monkeypatch) -> None:
    submitter = current_user()
    moderator = current_user(is_superuser=True)
    submission = submission_record(
        submitter_user_id=submitter.id,
        owner_user_id=submitter.id,
        status="approved",
    )
    submission.server_json["_meta"].pop("categories", None)

    async def get_submission(*args, **kwargs):
        return submission

    async def allow_submission_type(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)
    monkeypatch.setattr(service, "ensure_submission_type_allowed", allow_submission_type)

    with pytest.raises(SubmissionValidationError, match="at least one category is required"):
        await service.publish_submission(FakeSession(), moderator, submission.id)


@pytest.mark.asyncio
async def test_submit_submission_emits_event_record(monkeypatch) -> None:
    submitter = current_user()
    submission = submission_record(
        submitter_user_id=submitter.id,
        owner_user_id=submitter.id,
        status="draft",
    )

    async def no_published_version(*args, **kwargs):
        return None

    async def get_submission(*args, **kwargs):
        return submission

    monkeypatch.setattr(service.registry_repository, "get_server_version", no_published_version)
    monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)
    session = FakeSession()

    await service.submit_submission(session, submitter, submission.id)

    event = next(item for item in session.added if isinstance(item, EventRecord))
    assert event.event_type == "submission.submitted"
    assert event.owner_user_id == submitter.id
    assert event.payload["submission"]["id"] == str(submission.id)
    assert event.payload["submission"]["status"] == "submitted"
    assert event.payload["links"]["submissionApiUrl"] == f"/api/v1/submissions/{submission.id}"


@pytest.mark.asyncio
async def test_submission_catalog_event_types_emit_event_records(monkeypatch) -> None:
    submitter = current_user()
    moderator = current_user(is_global_moderator=True)
    published_version_id = uuid4()

    async def no_published_version(*args, **kwargs):
        return None

    async def publish_version(*args, **kwargs):
        return SimpleNamespace(version=SimpleNamespace(id=published_version_id))

    monkeypatch.setattr(service.registry_repository, "get_server_version", no_published_version)
    monkeypatch.setattr(service.registry_service, "create_server_version", publish_version)

    async def assert_emits(event_type: str, callback, *, expected_status: str) -> None:
        session = FakeSession()
        await callback(session)
        event = next(item for item in session.added if isinstance(item, EventRecord))
        assert event.event_type == event_type
        assert event.payload["submission"]["status"] == expected_status
        assert event.payload["eventType"] == event_type

    await assert_emits(
        "submission.created",
        lambda session: service.create_submission(
            session,
            submitter,
            SubmissionCreate(serverJson=complete_registry_payload()),
        ),
        expected_status="draft",
    )

    async def update_action(session):
        submission = submission_record(
            submitter_user_id=submitter.id,
            owner_user_id=submitter.id,
            status="draft",
        )

        async def get_submission(*args, **kwargs):
            return submission

        monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)
        await service.update_submission(
            session,
            submitter,
            submission.id,
            SubmissionUpdate(serverJson=complete_registry_payload(version="1.0.1")),
        )

    await assert_emits("submission.updated", update_action, expected_status="draft")

    async def withdraw_action(session):
        submission = submission_record(
            submitter_user_id=submitter.id,
            owner_user_id=submitter.id,
            status="submitted",
        )

        async def get_submission(*args, **kwargs):
            return submission

        monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)
        await service.withdraw_submission(session, submitter, submission.id)

    await assert_emits("submission.withdrawn", withdraw_action, expected_status="withdrawn")

    async def approve_action(session):
        submission = submission_record(
            submitter_user_id=submitter.id,
            owner_user_id=submitter.id,
            status="submitted",
        )

        async def get_submission(*args, **kwargs):
            return submission

        monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)
        await service.approve_submission(session, moderator, submission.id)

    await assert_emits("submission.approved", approve_action, expected_status="approved")

    async def reject_action(session):
        submission = submission_record(
            submitter_user_id=submitter.id,
            owner_user_id=submitter.id,
            status="submitted",
        )

        async def get_submission(*args, **kwargs):
            return submission

        monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)
        await service.reject_submission(session, moderator, submission.id, "Needs changes.")

    await assert_emits("submission.rejected", reject_action, expected_status="rejected")

    async def publish_action(session):
        submission = submission_record(
            submitter_user_id=submitter.id,
            owner_user_id=submitter.id,
            status="approved",
        )

        async def get_submission(*args, **kwargs):
            return submission

        monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)
        await service.publish_submission(session, moderator, submission.id)

    await assert_emits("submission.published", publish_action, expected_status="published")

    async def delete_action(session):
        submission = submission_record(
            submitter_user_id=submitter.id,
            owner_user_id=submitter.id,
            status="draft",
        )

        async def get_submission(*args, **kwargs):
            return submission

        monkeypatch.setattr(service.repository, "get_submission_by_id", get_submission)
        await service.delete_submission(session, submitter, submission.id)

    await assert_emits("submission.deleted", delete_action, expected_status="draft")


@pytest.mark.asyncio
async def test_submit_submission_rejects_incomplete_source_review(monkeypatch) -> None:
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

    with pytest.raises(SubmissionValidationError, match="not ready for review"):
        await service.submit_submission(FakeSession(), submitter, submission.id)


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


@pytest.mark.asyncio
async def test_delete_submission_removes_own_unpublished_submission(monkeypatch) -> None:
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
    session = FakeSession()

    await service.delete_submission(session, submitter, submission.id)

    assert submission in session.deleted
    assert session.flushed
    assert any(
        getattr(event, "event_type", "") == "submission.deleted"
        for event in session.added
    )


@pytest.mark.asyncio
async def test_delete_submission_rejects_other_submitter(monkeypatch) -> None:
    submitter = current_user()
    other_user = current_user()
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

    with pytest.raises(SubmissionAccessDeniedError, match="submission access denied"):
        await service.delete_submission(FakeSession(), other_user, submission.id)


@pytest.mark.asyncio
async def test_delete_submission_rejects_published(monkeypatch) -> None:
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
        await service.delete_submission(FakeSession(), submitter, submission.id)
