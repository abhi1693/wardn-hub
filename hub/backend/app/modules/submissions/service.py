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
from app.modules.users.models import User, UserAPIToken


def validation_check(name: str, status: str, message: str = "") -> dict[str, str]:
    return {"name": name, "status": status, "message": message}


def is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def has_http_url(value: Any) -> bool:
    if not is_non_empty_string(value):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def model_or_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        payload = value.model_dump(by_alias=True, exclude_none=True)
        return payload if isinstance(payload, dict) else {}
    return {}


def has_env_placeholder(value: Any) -> bool:
    return isinstance(value, str) and "${" in value and "}" in value


def collect_env_placeholders(value: Any, path: str = "serverJson") -> list[str]:
    if has_env_placeholder(value):
        return [path]
    if isinstance(value, dict):
        placeholders: list[str] = []
        for key, child_value in value.items():
            if key == "documentation":
                continue
            placeholders.extend(collect_env_placeholders(child_value, f"{path}.{key}"))
        return placeholders
    if isinstance(value, list):
        placeholders: list[str] = []
        for index, child_value in enumerate(value):
            placeholders.extend(collect_env_placeholders(child_value, f"{path}[{index}]"))
        return placeholders
    return []


def package_identifier_version_separator(identifier: str) -> str:
    value = identifier.strip()
    last_colon = value.rfind(":")
    last_slash = value.rfind("/")
    if last_colon > last_slash and last_colon < len(value) - 1:
        return ":"
    if "==" in value:
        name, _, version = value.partition("==")
        if name and version:
            return "=="
    at_index = value.rfind("@")
    if at_index > 0 and at_index < len(value) - 1:
        return "@"
    return ""


def package_targets_check(packages: list[Any]) -> dict[str, str]:
    if not packages:
        return validation_check("packages", "passed", "No package targets provided.")
    for package_value in packages:
        package = model_or_dict(package_value)
        if not is_non_empty_string(package.get("registryType")):
            return validation_check("packages", "failed", "Package registryType is required.")
        if not is_non_empty_string(package.get("identifier")):
            return validation_check("packages", "failed", "Package identifier is required.")
        identifier = str(package.get("identifier") or "")
        separator = package_identifier_version_separator(identifier)
        if separator:
            return validation_check(
                "packages",
                "failed",
                "Package identifier must not include a version. Move the "
                f"`{separator}` version suffix from {identifier} into the package version field.",
            )
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


def remote_targets_check(remotes: list[Any]) -> dict[str, str]:
    if not remotes:
        return validation_check("remotes", "passed", "No remote targets provided.")
    for remote_value in remotes:
        remote = model_or_dict(remote_value)
        if not has_http_url(remote.get("url")):
            return validation_check("remotes", "failed", "Remote target URL must be http or https.")
        if "type" in remote and not is_non_empty_string(remote.get("type")):
            return validation_check("remotes", "failed", "Remote target type is required.")
    return validation_check("remotes", "passed", "Remote targets are structurally valid.")


def env_placeholder_check(payload: RegistryServerVersionCreate) -> dict[str, str]:
    placeholders = collect_env_placeholders(payload.model_dump(by_alias=True, exclude_none=True))
    if placeholders:
        return validation_check(
            "envPlaceholders",
            "failed",
            "Environment placeholders are not allowed in submitted metadata: "
            + ", ".join(placeholders[:5]),
        )
    return validation_check("envPlaceholders", "passed", "No environment placeholders found.")


def duplicate_names(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []

    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        name = value.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        normalized = name.strip()
        if normalized in seen:
            duplicates.add(normalized)
        seen.add(normalized)
    return sorted(duplicates)


def duplicate_environment_check(payload: RegistryServerVersionCreate) -> dict[str, str]:
    data = payload.model_dump(by_alias=True, exclude_none=True)
    duplicates: list[str] = []

    packages = data.get("packages") if isinstance(data.get("packages"), list) else []
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            continue
        package_duplicates = duplicate_names(package.get("environmentVariables"))
        if package_duplicates:
            identifier = package.get("identifier")
            label = (
                identifier
                if isinstance(identifier, str) and identifier
                else f"package {index + 1}"
            )
            duplicates.append(f"{label}: {', '.join(package_duplicates)}")

    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    source_review = (
        meta.get("sourceReview")
        if isinstance(meta.get("sourceReview"), dict)
        else {}
    )
    source_review_duplicates = duplicate_names(source_review.get("environmentVariables"))
    if source_review_duplicates:
        duplicates.append("sourceReview: " + ", ".join(source_review_duplicates))

    if duplicates:
        return validation_check(
            "duplicateEnvironmentVariables",
            "failed",
            "Duplicate environment variable names are not allowed: " + "; ".join(duplicates),
        )
    return validation_check(
        "duplicateEnvironmentVariables",
        "passed",
        "Environment variable names are unique.",
    )


def readable_review_item(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if not isinstance(value, dict):
        return False
    return any(
        isinstance(value.get(key), str) and value.get(key, "").strip()
        for key in ("flag", "name", "value", "default", "description")
    )


def source_review_list_quality_check(payload: RegistryServerVersionCreate) -> dict[str, str]:
    meta = payload.meta if isinstance(payload.meta, dict) else {}
    source_review = meta.get("sourceReview") if isinstance(meta.get("sourceReview"), dict) else {}
    invalid_fields: list[str] = []

    for field in ("filesRead", "installCommands", "commandArguments", "prerequisites"):
        value = source_review.get(field)
        if not isinstance(value, list):
            continue
        if any(not readable_review_item(item) for item in value):
            invalid_fields.append(field)

    if invalid_fields:
        return validation_check(
            "sourceReviewFormat",
            "failed",
            "Source review entries must be readable strings or objects with "
            "flag/name/value/default/description: "
            + ", ".join(invalid_fields),
        )
    return validation_check("sourceReviewFormat", "passed", "Source review entries are readable.")


def package_transport_detail_check(packages: list[Any]) -> dict[str, str]:
    if not packages:
        return validation_check("packageTransportDetails", "passed", "No package targets provided.")

    incomplete: list[str] = []
    for package_value in packages:
        package = model_or_dict(package_value)
        registry_type = str(package.get("registryType") or "").lower()
        if registry_type == "mcpb":
            continue

        transport = package.get("transport")
        transport_value = transport if isinstance(transport, dict) else {}
        transport_type = str(transport_value.get("type") or "").lower()
        if transport_type and transport_type not in {"stdio", "local"}:
            continue

        identifier = str(package.get("identifier") or "package")
        missing: list[str] = []
        if not is_non_empty_string(transport_value.get("command")):
            missing.append("command")
        if not transport_value.get("args"):
            missing.append("args")
        if missing:
            incomplete.append(f"{identifier} missing {'/'.join(missing)}")

    if incomplete:
        return validation_check(
            "packageTransportDetails",
            "warning",
            "Package transport details may be incomplete: " + "; ".join(incomplete),
        )
    return validation_check(
        "packageTransportDetails",
        "passed",
        "Package transport command and args are present where expected.",
    )


def has_local_package_target(packages: list[Any]) -> bool:
    for package_value in packages:
        package = model_or_dict(package_value)
        registry_type = str(package.get("registryType") or "").lower()
        if registry_type == "mcpb":
            continue
        transport = package.get("transport")
        transport_value = transport if isinstance(transport, dict) else {}
        transport_type = str(transport_value.get("type") or "").lower()
        if not transport_type or transport_type in {"stdio", "local"}:
            return True
    return False


def documentation_detail_check(payload: RegistryServerVersionCreate) -> dict[str, str]:
    documentation = payload.documentation.lower()
    if not documentation.strip():
        return validation_check("documentationDetails", "warning", "Documentation is empty.")

    missing_sections = [
        label
        for label, needles in {
            "installation": ("installation", "install", "mcpservers", "command"),
            "configuration": ("configuration", "environment", "env", "args", "variables"),
            "capabilities": ("capabilities", "tools", "resources", "prompts"),
        }.items()
        if not any(needle in documentation for needle in needles)
    ]
    if missing_sections:
        return validation_check(
            "documentationDetails",
            "warning",
            "Documentation may be missing: " + ", ".join(missing_sections),
        )
    return validation_check(
        "documentationDetails",
        "passed",
        "Documentation includes setup, configuration, and capability details.",
    )


def source_review_check(payload: RegistryServerVersionCreate) -> dict[str, str]:
    meta = payload.meta if isinstance(payload.meta, dict) else {}
    source_review = meta.get("sourceReview") if isinstance(meta.get("sourceReview"), dict) else {}
    files_read = (
        source_review.get("filesRead")
        if isinstance(source_review.get("filesRead"), list)
        else []
    )
    unknowns = (
        source_review.get("unknowns")
        if isinstance(source_review.get("unknowns"), list)
        else []
    )
    missing: list[str] = []
    if not files_read:
        missing.append("filesRead")
    if source_review.get("capabilitiesReviewed") is not True:
        missing.append("capabilitiesReviewed")
    if source_review.get("limitationsReviewed") is not True:
        missing.append("limitationsReviewed")
    if unknowns:
        missing.append("unknowns must be resolved")
    if has_local_package_target(payload.packages):
        install_commands = source_review.get("installCommands")
        command_arguments = source_review.get("commandArguments")
        if not isinstance(install_commands, list) or not install_commands:
            missing.append("installCommands")
        if not isinstance(command_arguments, list) or not command_arguments:
            missing.append("commandArguments")

    if missing:
        return validation_check(
            "sourceReview",
            "warning",
            "Source review evidence is incomplete: " + ", ".join(missing),
        )
    return validation_check("sourceReview", "passed", "Source review evidence is complete.")


def documentation_check(payload: RegistryServerVersionCreate) -> dict[str, str]:
    if payload.documentation.strip():
        return validation_check("documentation", "passed", "Documentation is present.")
    return validation_check("documentation", "warning", "Documentation is empty.")


def validation_result_for(payload: RegistryServerVersionCreate) -> dict:
    checks = [
        validation_check("schema", "passed", "Registry schema fields are valid."),
        validation_check("target", "passed", "At least one package or remote target is present."),
        env_placeholder_check(payload),
        duplicate_environment_check(payload),
        source_review_list_quality_check(payload),
        package_targets_check(payload.packages),
        package_transport_detail_check(payload.packages),
        remote_targets_check(payload.remotes),
        documentation_check(payload),
        documentation_detail_check(payload),
        source_review_check(payload),
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


def ensure_ready_for_review(validation_result: dict) -> None:
    ensure_validation_passed(validation_result)
    warnings = [
        check["message"]
        for check in validation_result.get("checks", [])
        if check.get("status") == "warning" and check.get("message")
    ]
    if warnings:
        raise SubmissionValidationError(
            "submission is not ready for review: " + "; ".join(warnings)
        )


def can_review_submissions(user: User) -> bool:
    return user.is_superuser or user.is_global_moderator


def api_token_organization_ids(api_token: UserAPIToken | None) -> set[str]:
    if api_token is None:
        return set()
    return {str(organization_id) for organization_id in api_token.organization_ids}


def ensure_api_token_organization_access(
    api_token: UserAPIToken | None,
    owner_organization_id: uuid.UUID | None,
) -> None:
    allowed_organization_ids = api_token_organization_ids(api_token)
    if not allowed_organization_ids:
        return
    if owner_organization_id is None or str(owner_organization_id) not in allowed_organization_ids:
        raise SubmissionAccessDeniedError("API token organization access denied")


def ensure_api_token_submission_access(
    api_token: UserAPIToken | None,
    submission: ServerSubmission,
) -> None:
    ensure_api_token_organization_access(api_token, submission.owner_organization_id)


def filter_submissions_for_api_token(
    api_token: UserAPIToken | None,
    submissions: list[ServerSubmission],
) -> list[ServerSubmission]:
    allowed_organization_ids = api_token_organization_ids(api_token)
    if not allowed_organization_ids:
        return submissions
    return [
        submission
        for submission in submissions
        if submission.owner_organization_id is not None
        and str(submission.owner_organization_id) in allowed_organization_ids
    ]


async def resolve_submission_owner(
    session: AsyncSession,
    user: User,
    *,
    owner_user_id: uuid.UUID | None,
    owner_organization_id: uuid.UUID | None,
    permission: str,
    api_token: UserAPIToken | None = None,
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
    ensure_api_token_organization_access(api_token, owner_organization_id)
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
    if not can_review_submissions(user) and submission.submitter_user_id != user.id:
        raise SubmissionAccessDeniedError("submission access denied")


def ensure_can_own_or_manage_submission(user: User, submission: ServerSubmission) -> None:
    if not user.is_superuser and submission.submitter_user_id != user.id:
        raise SubmissionAccessDeniedError("submission access denied")


def ensure_can_mutate_submission(user: User, submission: ServerSubmission) -> None:
    ensure_can_own_or_manage_submission(user, submission)
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
    *,
    api_token: UserAPIToken | None = None,
) -> SubmissionRead:
    submission = await repository.get_submission_by_id(session, submission_id)
    if submission is None:
        raise SubmissionNotFoundError("submission not found")
    ensure_can_read_submission(user, submission)
    ensure_api_token_submission_access(api_token, submission)
    return submission_response(submission)


async def list_submissions(
    session: AsyncSession,
    user: User,
    *,
    api_token: UserAPIToken | None = None,
) -> SubmissionListResponse:
    submissions = await repository.list_submissions(
        session,
        user_id=user.id,
        include_all=can_review_submissions(user),
    )
    submissions = filter_submissions_for_api_token(api_token, submissions)
    return SubmissionListResponse(
        submissions=[submission_response(submission) for submission in submissions]
    )


async def create_submission(
    session: AsyncSession,
    user: User,
    payload: SubmissionCreate,
    *,
    api_token: UserAPIToken | None = None,
) -> SubmissionRead:
    validation_result = validation_result_for(payload.server_json)
    ensure_validation_passed(validation_result)
    owner_user_id, owner_organization_id = await resolve_submission_owner(
        session,
        user,
        owner_user_id=payload.owner_user_id,
        owner_organization_id=payload.owner_organization_id,
        permission="servers.create",
        api_token=api_token,
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
    *,
    api_token: UserAPIToken | None = None,
) -> SubmissionRead:
    submission = await repository.get_submission_by_id(session, submission_id)
    if submission is None:
        raise SubmissionNotFoundError("submission not found")
    ensure_can_mutate_submission(user, submission)
    ensure_api_token_submission_access(api_token, submission)

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
        api_token=api_token,
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


async def delete_submission(
    session: AsyncSession,
    user: User,
    submission_id: uuid.UUID,
    *,
    api_token: UserAPIToken | None = None,
) -> None:
    submission = await repository.get_submission_by_id(session, submission_id)
    if submission is None:
        raise SubmissionNotFoundError("submission not found")
    ensure_can_mutate_submission(user, submission)
    ensure_api_token_submission_access(api_token, submission)
    await emit_audit_event(
        session,
        event_type="submission.deleted",
        subject_type="server_submission",
        subject_id=submission.id,
        actor_user_id=user.id,
        organization_id=submission.owner_organization_id,
        metadata={
            "name": submission.name,
            "version": submission.version,
            "status": submission.status,
        },
    )
    await repository.delete_submission(session, submission)


async def submit_submission(
    session: AsyncSession,
    user: User,
    submission_id: uuid.UUID,
    *,
    api_token: UserAPIToken | None = None,
) -> SubmissionRead:
    submission = await repository.get_submission_by_id(session, submission_id)
    if submission is None:
        raise SubmissionNotFoundError("submission not found")
    ensure_can_own_or_manage_submission(user, submission)
    ensure_api_token_submission_access(api_token, submission)
    if submission.status not in {"draft", "rejected"}:
        raise InvalidSubmissionTransitionError("submission cannot be submitted")
    payload = RegistryServerVersionCreate.model_validate(submission.server_json)
    validation_result = validation_result_for(payload)
    ensure_ready_for_review(validation_result)
    submission.validation_result = validation_result
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
    *,
    api_token: UserAPIToken | None = None,
) -> SubmissionRead:
    submission = await repository.get_submission_by_id(session, submission_id)
    if submission is None:
        raise SubmissionNotFoundError("submission not found")
    ensure_can_own_or_manage_submission(user, submission)
    ensure_api_token_submission_access(api_token, submission)
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
    *,
    api_token: UserAPIToken | None = None,
) -> SubmissionRead:
    submission = await repository.get_submission_by_id(session, submission_id)
    if submission is None:
        raise SubmissionNotFoundError("submission not found")
    ensure_api_token_submission_access(api_token, submission)
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
    *,
    api_token: UserAPIToken | None = None,
) -> SubmissionRead:
    submission = await repository.get_submission_by_id(session, submission_id)
    if submission is None:
        raise SubmissionNotFoundError("submission not found")
    ensure_api_token_submission_access(api_token, submission)
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
    *,
    api_token: UserAPIToken | None = None,
) -> SubmissionRead:
    submission = await repository.get_submission_by_id(session, submission_id)
    if submission is None:
        raise SubmissionNotFoundError("submission not found")
    ensure_api_token_submission_access(api_token, submission)
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
