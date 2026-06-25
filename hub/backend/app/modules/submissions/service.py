import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import emit_audit_event
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
)
from app.modules.organizations.service import require_organization_permission
from app.modules.registry import repository as registry_repository
from app.modules.registry import service as registry_service
from app.modules.registry.exceptions import DuplicateRegistryVersionError
from app.modules.registry.schemas import RegistryServerVersionCreate
from app.modules.submissions import repository
from app.modules.submissions.exceptions import (
    DuplicatePublishedVersionError,
    InvalidSubmissionTransitionError,
    SubmissionAccessDeniedError,
    SubmissionNotFoundError,
    SubmissionValidationError,
)
from app.modules.submissions.models import ServerSubmission
from app.modules.submissions.schemas import (
    SubmissionCreate,
    SubmissionListResponse,
    SubmissionRead,
    SubmissionUpdate,
)
from app.modules.users.models import User


def validation_check(name: str, status: str, message: str = "") -> dict[str, str]:
    return {"name": name, "status": status, "message": message}


def is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def has_http_url(value: Any) -> bool:
    if not is_non_empty_string(value):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def package_targets_check(packages: list[dict[str, Any]]) -> dict[str, str]:
    if not packages:
        return validation_check("packages", "passed", "No package targets provided.")
    for package in packages:
        if not is_non_empty_string(package.get("registryType")):
            return validation_check("packages", "failed", "Package registryType is required.")
        if not is_non_empty_string(package.get("identifier")):
            return validation_check("packages", "failed", "Package identifier is required.")
        transport = package.get("transport")
        if transport is not None:
            if not isinstance(transport, dict):
                return validation_check(
                    "packages",
                    "failed",
                    "Package transport must be an object.",
                )
            if "type" in transport and not is_non_empty_string(transport.get("type")):
                return validation_check("packages", "failed", "Package transport type is required.")
    return validation_check("packages", "passed", "Package targets are structurally valid.")


def remote_targets_check(remotes: list[dict[str, Any]]) -> dict[str, str]:
    if not remotes:
        return validation_check("remotes", "passed", "No remote targets provided.")
    for remote in remotes:
        if not has_http_url(remote.get("url")):
            return validation_check("remotes", "failed", "Remote target URL must be http or https.")
        if "type" in remote and not is_non_empty_string(remote.get("type")):
            return validation_check("remotes", "failed", "Remote target type is required.")
    return validation_check("remotes", "passed", "Remote targets are structurally valid.")


def documentation_check(payload: RegistryServerVersionCreate) -> dict[str, str]:
    if payload.documentation.strip():
        return validation_check("documentation", "passed", "Documentation is present.")
    return validation_check("documentation", "warning", "Documentation is empty.")


def validation_result_for(payload: RegistryServerVersionCreate) -> dict:
    checks = [
        validation_check("schema", "passed", "Registry schema fields are valid."),
        validation_check("target", "passed", "At least one package or remote target is present."),
        package_targets_check(payload.packages),
        remote_targets_check(payload.remotes),
        documentation_check(payload),
    ]
    statuses = {check["status"] for check in checks}
    status = "failed" if "failed" in statuses else "warning" if "warning" in statuses else "passed"
    return {"status": status, "checks": checks}


def ensure_validation_passed(validation_result: dict) -> None:
    if validation_result["status"] != "failed":
        return
    failed = [
        check["message"]
        for check in validation_result["checks"]
        if check["status"] == "failed" and check.get("message")
    ]
    message = failed[0] if failed else "submission payload validation failed"
    raise SubmissionValidationError(message)


async def resolve_submission_owner(
    session: AsyncSession,
    user: User,
    *,
    owner_user_id: uuid.UUID | None,
    owner_organization_id: uuid.UUID | None,
    permission: str,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    if owner_user_id is None and owner_organization_id is None:
        owner_user_id = user.id
    if owner_user_id is not None and not user.is_superuser and owner_user_id != user.id:
        raise SubmissionAccessDeniedError("submission owner user access denied")
    if owner_organization_id is not None:
        try:
            await require_organization_permission(session, user, owner_organization_id, permission)
        except OrganizationNotFoundError as exc:
            raise SubmissionValidationError("owner organization not found") from exc
        except OrganizationAccessDeniedError as exc:
            raise SubmissionAccessDeniedError("owner organization access denied") from exc
    return owner_user_id, owner_organization_id


def submission_response(submission: ServerSubmission) -> SubmissionRead:
    return SubmissionRead(
        id=submission.id,
        name=submission.name,
        version=submission.version,
        submitterUserId=submission.submitter_user_id,
        ownerUserId=submission.owner_user_id,
        ownerOrganizationId=submission.owner_organization_id,
        submissionType=submission.submission_type,
        status=submission.status,
        serverJson=submission.server_json,
        validationResult=submission.validation_result,
        submittedAt=submission.submitted_at,
        approvedAt=submission.approved_at,
        approverUserId=submission.approver_user_id,
        rejectionMessage=submission.rejection_message,
        publishedServerVersionId=submission.published_server_version_id,
        createdAt=submission.created_at,
        updatedAt=submission.updated_at,
    )


def ensure_can_read_submission(user: User, submission: ServerSubmission) -> None:
    if not user.is_superuser and submission.submitter_user_id != user.id:
        raise SubmissionAccessDeniedError("submission access denied")


def ensure_can_mutate_submission(user: User, submission: ServerSubmission) -> None:
    ensure_can_read_submission(user, submission)
    if submission.status == "published":
        raise InvalidSubmissionTransitionError("published submissions cannot be edited")


async def ensure_version_not_published(
    session: AsyncSession,
    name: str,
    version: str,
) -> None:
    existing = await registry_repository.get_server_version(
        session,
        name,
        version,
        include_deleted=True,
    )
    if existing is not None and existing.status != "deleted":
        raise DuplicatePublishedVersionError("server version already published")


async def ensure_submission_type_allowed(
    session: AsyncSession,
    submission_type: str,
    name: str,
) -> None:
    if submission_type != "new_version":
        return

    server = await registry_repository.get_server(session, name)
    if server is None:
        raise SubmissionValidationError("new version submissions require a published server")


async def get_submission(
    session: AsyncSession,
    user: User,
    submission_id: uuid.UUID,
) -> SubmissionRead:
    submission = await repository.get_submission_by_id(session, submission_id)
    if submission is None:
        raise SubmissionNotFoundError("submission not found")
    ensure_can_read_submission(user, submission)
    return submission_response(submission)


async def list_submissions(
    session: AsyncSession,
    user: User,
) -> SubmissionListResponse:
    submissions = await repository.list_submissions(
        session,
        user_id=user.id,
        include_all=user.is_superuser,
    )
    return SubmissionListResponse(
        submissions=[submission_response(submission) for submission in submissions]
    )


async def create_submission(
    session: AsyncSession,
    user: User,
    payload: SubmissionCreate,
) -> SubmissionRead:
    validation_result = validation_result_for(payload.server_json)
    ensure_validation_passed(validation_result)
    owner_user_id, owner_organization_id = await resolve_submission_owner(
        session,
        user,
        owner_user_id=payload.owner_user_id,
        owner_organization_id=payload.owner_organization_id,
        permission="servers.create",
    )
    await ensure_submission_type_allowed(
        session,
        payload.submission_type,
        payload.server_json.name,
    )
    await ensure_version_not_published(
        session,
        payload.server_json.name,
        payload.server_json.version,
    )
    submission = ServerSubmission(
        name=payload.server_json.name,
        version=payload.server_json.version,
        submitter_user_id=user.id,
        owner_user_id=owner_user_id,
        owner_organization_id=owner_organization_id,
        submission_type=payload.submission_type,
        status="draft",
        server_json=payload.server_json.model_dump(by_alias=True, exclude_none=True),
        validation_result=validation_result,
    )
    session.add(submission)
    await session.flush()
    await session.refresh(submission)
    await emit_audit_event(
        session,
        event_type="submission.created",
        subject_type="server_submission",
        subject_id=submission.id,
        actor_user_id=user.id,
        organization_id=submission.owner_organization_id,
        metadata={"name": submission.name, "version": submission.version},
    )
    return submission_response(submission)


async def update_submission(
    session: AsyncSession,
    user: User,
    submission_id: uuid.UUID,
    payload: SubmissionUpdate,
) -> SubmissionRead:
    submission = await repository.get_submission_by_id(session, submission_id)
    if submission is None:
        raise SubmissionNotFoundError("submission not found")
    ensure_can_mutate_submission(user, submission)

    server_json = payload.server_json
    if server_json is not None:
        validation_result = validation_result_for(server_json)
        ensure_validation_passed(validation_result)
        await ensure_version_not_published(session, server_json.name, server_json.version)
        submission.name = server_json.name
        submission.version = server_json.version
        submission.server_json = server_json.model_dump(by_alias=True, exclude_none=True)
        submission.validation_result = validation_result
    if payload.submission_type is not None:
        submission.submission_type = payload.submission_type
    await ensure_submission_type_allowed(session, submission.submission_type, submission.name)
    next_owner_user_id = (
        payload.owner_user_id
        if "owner_user_id" in payload.model_fields_set
        else submission.owner_user_id
    )
    next_owner_organization_id = (
        payload.owner_organization_id
        if "owner_organization_id" in payload.model_fields_set
        else submission.owner_organization_id
    )
    next_owner_user_id, next_owner_organization_id = await resolve_submission_owner(
        session,
        user,
        owner_user_id=next_owner_user_id,
        owner_organization_id=next_owner_organization_id,
        permission="servers.update",
    )
    submission.owner_user_id = next_owner_user_id
    submission.owner_organization_id = next_owner_organization_id
    submission.status = "draft"
    submission.rejection_message = ""
    await session.flush()
    await session.refresh(submission)
    await emit_audit_event(
        session,
        event_type="submission.updated",
        subject_type="server_submission",
        subject_id=submission.id,
        actor_user_id=user.id,
        organization_id=submission.owner_organization_id,
        metadata={"name": submission.name, "version": submission.version},
    )
    return submission_response(submission)


async def submit_submission(
    session: AsyncSession,
    user: User,
    submission_id: uuid.UUID,
) -> SubmissionRead:
    submission = await repository.get_submission_by_id(session, submission_id)
    if submission is None:
        raise SubmissionNotFoundError("submission not found")
    ensure_can_read_submission(user, submission)
    if submission.status not in {"draft", "rejected"}:
        raise InvalidSubmissionTransitionError("submission cannot be submitted")
    await ensure_version_not_published(session, submission.name, submission.version)
    submission.status = "submitted"
    submission.submitted_at = datetime.now(UTC)
    submission.rejection_message = ""
    await session.flush()
    await session.refresh(submission)
    await emit_audit_event(
        session,
        event_type="submission.submitted",
        subject_type="server_submission",
        subject_id=submission.id,
        actor_user_id=user.id,
        organization_id=submission.owner_organization_id,
        metadata={"name": submission.name, "version": submission.version},
    )
    return submission_response(submission)


async def withdraw_submission(
    session: AsyncSession,
    user: User,
    submission_id: uuid.UUID,
) -> SubmissionRead:
    submission = await repository.get_submission_by_id(session, submission_id)
    if submission is None:
        raise SubmissionNotFoundError("submission not found")
    ensure_can_read_submission(user, submission)
    if submission.status != "submitted":
        raise InvalidSubmissionTransitionError("only submitted submissions can be withdrawn")
    submission.status = "withdrawn"
    await session.flush()
    await session.refresh(submission)
    await emit_audit_event(
        session,
        event_type="submission.withdrawn",
        subject_type="server_submission",
        subject_id=submission.id,
        actor_user_id=user.id,
        organization_id=submission.owner_organization_id,
        metadata={"name": submission.name, "version": submission.version},
    )
    return submission_response(submission)


async def approve_submission(
    session: AsyncSession,
    approver: User,
    submission_id: uuid.UUID,
) -> SubmissionRead:
    submission = await repository.get_submission_by_id(session, submission_id)
    if submission is None:
        raise SubmissionNotFoundError("submission not found")
    if submission.status != "submitted":
        raise InvalidSubmissionTransitionError("only submitted submissions can be approved")
    await ensure_version_not_published(session, submission.name, submission.version)
    submission.status = "approved"
    submission.approved_at = datetime.now(UTC)
    submission.approver_user_id = approver.id
    submission.rejection_message = ""
    await session.flush()
    await session.refresh(submission)
    await emit_audit_event(
        session,
        event_type="submission.approved",
        subject_type="server_submission",
        subject_id=submission.id,
        actor_user_id=approver.id,
        organization_id=submission.owner_organization_id,
        metadata={"name": submission.name, "version": submission.version},
    )
    return submission_response(submission)


async def reject_submission(
    session: AsyncSession,
    approver: User,
    submission_id: uuid.UUID,
    message: str,
) -> SubmissionRead:
    submission = await repository.get_submission_by_id(session, submission_id)
    if submission is None:
        raise SubmissionNotFoundError("submission not found")
    if submission.status != "submitted":
        raise InvalidSubmissionTransitionError("only submitted submissions can be rejected")
    submission.status = "rejected"
    submission.approver_user_id = approver.id
    submission.rejection_message = message.strip()
    await session.flush()
    await session.refresh(submission)
    await emit_audit_event(
        session,
        event_type="submission.rejected",
        subject_type="server_submission",
        subject_id=submission.id,
        actor_user_id=approver.id,
        organization_id=submission.owner_organization_id,
        metadata={"name": submission.name, "version": submission.version},
    )
    return submission_response(submission)


async def publish_submission(
    session: AsyncSession,
    publisher: User,
    submission_id: uuid.UUID,
) -> SubmissionRead:
    submission = await repository.get_submission_by_id(session, submission_id)
    if submission is None:
        raise SubmissionNotFoundError("submission not found")
    if submission.status != "approved":
        raise InvalidSubmissionTransitionError("only approved submissions can be published")
    payload = RegistryServerVersionCreate.model_validate(submission.server_json)
    try:
        published = await registry_service.create_server_version(
            session,
            payload,
            owner_user_id=submission.owner_user_id,
            owner_organization_id=submission.owner_organization_id,
            created_by_user_id=submission.submitter_user_id,
            updated_by_user_id=publisher.id,
            publisher_user_id=publisher.id,
        )
    except DuplicateRegistryVersionError as exc:
        raise DuplicatePublishedVersionError("server version already published") from exc
    submission.status = "published"
    submission.published_server_version_id = published.version.id
    await session.flush()
    await session.refresh(submission)
    await emit_audit_event(
        session,
        event_type="submission.published",
        subject_type="server_submission",
        subject_id=submission.id,
        actor_user_id=publisher.id,
        organization_id=submission.owner_organization_id,
        metadata={
            "name": submission.name,
            "version": submission.version,
            "publishedServerVersionId": str(published.version.id),
        },
    )
    return submission_response(submission)
