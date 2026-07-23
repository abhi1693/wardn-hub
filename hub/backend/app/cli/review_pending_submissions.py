# ruff: noqa: E501

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
from collections.abc import Iterable
from typing import Any, Literal, Protocol, TextIO

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.cli.codex_app_server import (
    CodexAppServerReviewer,
    UserFacingError,
)
from app.core.codex import CODEX_APP_SERVER_AUTH_TOKEN_ENV, CODEX_APP_SERVER_URL_ENV

REVIEW_PROMPT_CHAR_LIMIT = 900_000
REVIEW_JSON_STRING_LIMIT = 20_000
REVIEW_JSON_LIST_LIMIT = 200

SYSTEM_REVIEW_INSTRUCTIONS = """System review mode:
- Use the submission JSON snapshot and submitted MCP server model JSON in this prompt as the Wardn Hub source of truth.
- Do not call Wardn Hub API endpoints.
- Do not request or expose Wardn Hub credentials.
- Review upstream public source repositories, README files, documentation, and package metadata only."""

REGISTRY_METADATA_SCOPE_RULE = (
    "Treat this as registry metadata review only. Do not install workspace MCP servers, "
    "invoke MCP tools, or manage runtime infrastructure."
)

VALIDATION_PACKAGE_ARGUMENT_CHECKS = """- packages[].transport.args contains only the concrete default launch arguments in runnable order, not every documented optional CLI flag.
- Optional CLI flags/configurable arguments are represented in packages[].packageArguments with includeInLaunch false.
- Flags that take user-supplied values are represented with packageArguments[].requiresValue true, not placeholder text in transport.args.
- packageArguments[].value does not contain placeholder examples such as "<host>", "[url]", "host", or "url"; requiresValue is the metadata for that.
- packageArguments[].flag does not contain placeholders. For docs that show "--host <host>", the correct shape is flag "--host" and requiresValue true.
- Package arguments that are part of the default launch command have includeInLaunch true.
- packageArguments contain only server process args after the package/image, not package-manager wrapper args such as npx/npm/uvx/pipx/docker, install/run flags, or the package/image identifier."""

VALIDATION_REMOTE_QUERY_PARAMETER_CHECKS = """- Remote endpoint URLs do not include configurable query strings such as ?apiKey={apiKey}.
- Remote URL query parameters are represented in remotes[].queryParameters, not remotes[].authentication.queryParameters.
- If docs show a hosted URL with query authentication, the base endpoint is stored in remotes[].url and the query auth fields are stored in remotes[].queryParameters."""

NEW_SERVER_INITIAL_VERSION_MESSAGE = (
    "New server submissions must start at Wardn registry version 1.0.0. "
    "Keep upstream package, image, or server versions in packages[].version."
)


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["high", "medium", "low", "info"]
    message: str = Field(min_length=1, max_length=2000)


class ReviewDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    decision: Literal["pass", "needs_fixes", "reject", "cannot_validate", "skip"]
    suggested_rejection_message: str | None = Field(
        default=None,
        alias="suggestedRejectionMessage",
        max_length=2000,
    )
    suggested_approval_note: str | None = Field(
        default=None,
        alias="suggestedApprovalNote",
        max_length=2000,
    )
    findings: list[ReviewFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_action_notes(self) -> ReviewDecisionPayload:
        if self.decision in {"needs_fixes", "reject"} and not (
            self.suggested_rejection_message or ""
        ).strip():
            raise ValueError(
                "suggestedRejectionMessage is required when decision is needs_fixes or reject"
            )
        return self


REVIEW_DECISION_SCHEMA_JSON = json.dumps(
    ReviewDecisionPayload.model_json_schema(by_alias=True),
    indent=2,
    sort_keys=True,
)


TRANSIENT_DATABASE_DISCONNECT_SNIPPETS = (
    "connection was closed",
    "connection is closed",
    "server closed the connection",
    "connection reset",
    "connection refused",
    "connectiondoesnotexisterror",
)


def is_transient_database_disconnect(exc: BaseException) -> bool:
    from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

    if not isinstance(exc, DBAPIError | InterfaceError | OperationalError):
        return False
    message = str(exc).lower()
    return any(snippet in message for snippet in TRANSIENT_DATABASE_DISCONNECT_SNIPPETS)


def int_from_env(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise UserFacingError(f"${name} must be an integer") from exc


class Reviewer(Protocol):
    def review(self, prompt: str, *, environment: dict[str, str]) -> str:
        """Return review findings for a prompt."""


def submission_read_to_review_dict(submission: Any) -> dict[str, Any]:
    model_dump = getattr(submission, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json", by_alias=True)
    if isinstance(submission, dict):
        return submission
    return dict(submission)


class WardnHubDatabaseReviewClient:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()

    @property
    def is_system_review(self) -> bool:
        return True

    @property
    def is_database_review(self) -> bool:
        return True

    def _run_database_operation(self, operation: Any, *, commit: bool = False) -> Any:
        async def run() -> Any:
            from app.db.session import AsyncSessionLocal

            async with AsyncSessionLocal() as session:
                try:
                    result = await operation(session)
                    if commit:
                        await session.commit()
                    return result
                except Exception:
                    await session.rollback()
                    raise

        for attempt in range(2):
            try:
                return self._loop.run_until_complete(run())
            except Exception as exc:
                if commit or attempt == 1 or not is_transient_database_disconnect(exc):
                    raise
                time.sleep(1)
        raise RuntimeError("unreachable database retry state")

    def list_submissions(self) -> list[dict[str, Any]]:
        async def operation(session: Any) -> list[dict[str, Any]]:
            from app.modules.submissions.service import list_submissions_for_database_review

            submissions = await list_submissions_for_database_review(session)
            return [submission_read_to_review_dict(submission) for submission in submissions]

        return self._run_database_operation(operation)

    def next_submission(
        self,
        *,
        skipped_ids: set[str],
        submission_id: str | None,
    ) -> dict[str, Any] | None:
        async def operation(session: Any) -> dict[str, Any] | None:
            from app.modules.submissions.service import next_submission_for_database_review

            submission = await next_submission_for_database_review(
                session,
                exclude_ids={uuid.UUID(value) for value in skipped_ids},
                submission_id=uuid.UUID(submission_id) if submission_id else None,
            )
            return (
                submission_read_to_review_dict(submission)
                if submission is not None
                else None
            )

        return self._run_database_operation(operation)

    def get_submission(self, submission_id: str) -> dict[str, Any]:
        async def operation(session: Any) -> dict[str, Any]:
            from app.modules.submissions.service import get_submission_for_system_review

            submission = await get_submission_for_system_review(session, uuid.UUID(submission_id))
            return submission_read_to_review_dict(submission)

        return self._run_database_operation(operation)

    def approve_submission(self, submission_id: str) -> dict[str, Any]:
        async def operation(session: Any) -> dict[str, Any]:
            from app.modules.submissions.exceptions import SubmissionError
            from app.modules.submissions.service import approve_submission_by_system

            try:
                submission = await approve_submission_by_system(session, uuid.UUID(submission_id))
            except SubmissionError as exc:
                raise UserFacingError(f"Unable to approve submission: {exc}") from exc
            return submission_read_to_review_dict(submission)

        return self._run_database_operation(operation, commit=True)

    def publish_submission(self, submission_id: str) -> dict[str, Any]:
        async def operation(session: Any) -> dict[str, Any]:
            from app.modules.submissions.exceptions import SubmissionError
            from app.modules.submissions.service import publish_submission_by_system

            try:
                submission = await publish_submission_by_system(session, uuid.UUID(submission_id))
            except SubmissionError as exc:
                raise UserFacingError(f"Unable to publish submission: {exc}") from exc
            return submission_read_to_review_dict(submission)

        return self._run_database_operation(operation, commit=True)

    def reject_submission(self, submission_id: str, message: str) -> dict[str, Any]:
        async def operation(session: Any) -> dict[str, Any]:
            from app.modules.submissions.exceptions import SubmissionError
            from app.modules.submissions.service import reject_submission_by_system

            try:
                submission = await reject_submission_by_system(
                    session,
                    uuid.UUID(submission_id),
                    message,
                )
            except SubmissionError as exc:
                raise UserFacingError(f"Unable to reject submission: {exc}") from exc
            return submission_read_to_review_dict(submission)

        return self._run_database_operation(operation, commit=True)

    def probe_moderation_access(self) -> None:
        return None

    def probe_publish_access(self) -> bool:
        return True
def bool_field(data: dict[str, Any], snake_case: str, camel_case: str) -> bool:
    return bool(data.get(snake_case) or data.get(camel_case))


def validate_database_review_client(client: WardnHubDatabaseReviewClient) -> dict[str, Any]:
    next_submission = getattr(client, "next_submission", None)
    if callable(next_submission):
        next_submission(skipped_ids=set(), submission_id=None)
    else:
        client.list_submissions()
    client.probe_moderation_access()
    return {
        "id": "database",
        "display_name": "Wardn Hub database review",
        "email": "",
        "is_active": True,
        "is_superuser": False,
        "is_global_moderator": True,
        "is_database_review": True,
        "_wardnHubCanPublish": client.probe_publish_access(),
    }


def pending_submissions(
    submissions: Iterable[dict[str, Any]],
    *,
    skipped_ids: set[str],
) -> list[dict[str, Any]]:
    pending = [
        submission
        for submission in submissions
        if submission.get("status") == "submitted"
        and str(submission.get("id") or "") not in skipped_ids
    ]
    indexed_pending = list(enumerate(pending))
    indexed_pending.sort(key=lambda item: (submission_queue_timestamp(item[1]), item[0]))
    return [submission for _, submission in indexed_pending]


def submission_queue_timestamp(submission: dict[str, Any]) -> str:
    for field in ("submittedAt", "submitted_at", "createdAt", "created_at", "updatedAt", "updated_at"):
        value = submission.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "9999-12-31T23:59:59.999999Z"


def build_review_context(client: WardnHubDatabaseReviewClient, submission: dict[str, Any]) -> dict[str, Any]:
    submission_id = str(submission["id"])
    fresh_submission = client.get_submission(submission_id)
    return {
        "submission": fresh_submission,
    }


def submitted_mcp_server_model_json(submission: dict[str, Any]) -> dict[str, Any]:
    server_json = submission.get("serverJson")
    if not isinstance(server_json, dict):
        return {}
    try:
        from app.modules.registry.schemas import RegistryServerVersionCreate

        return RegistryServerVersionCreate.model_validate(server_json).to_json_dict()
    except ValueError:
        return server_json


def truncate_review_string(value: str, *, limit: int) -> str:
    if len(value) <= limit:
        return value
    omitted = len(value) - limit
    head_length = max(limit - 160, limit // 2)
    tail_length = max(limit - head_length, 0)
    suffix = value[-tail_length:] if tail_length else ""
    return (
        value[:head_length]
        + f"\n\n[Wardn review prompt truncated {omitted} characters from this string. "
        "Use upstream public sources for omitted long-form content.]\n\n"
        + suffix
    )


def compact_review_json(
    value: Any,
    *,
    string_limit: int = REVIEW_JSON_STRING_LIMIT,
    list_limit: int = REVIEW_JSON_LIST_LIMIT,
) -> Any:
    if isinstance(value, str):
        return truncate_review_string(value, limit=string_limit)
    if isinstance(value, list):
        compacted = [
            compact_review_json(item, string_limit=string_limit, list_limit=list_limit)
            for item in value[:list_limit]
        ]
        if len(value) > list_limit:
            compacted.append(
                {
                    "_wardnReviewPromptTruncated": (
                        f"{len(value) - list_limit} list items omitted"
                    )
                }
            )
        return compacted
    if isinstance(value, dict):
        return {
            str(key): compact_review_json(
                item,
                string_limit=string_limit,
                list_limit=list_limit,
            )
            for key, item in value.items()
        }
    return value


def submission_snapshot_for_review(
    submission: dict[str, Any],
    *,
    string_limit: int = REVIEW_JSON_STRING_LIMIT,
    list_limit: int = REVIEW_JSON_LIST_LIMIT,
) -> dict[str, Any]:
    snapshot = {key: value for key, value in submission.items() if key != "serverJson"}
    if "serverJson" in submission:
        snapshot["serverJson"] = (
            "[omitted from submission snapshot; see normalized Submitted MCP server model JSON below]"
        )
    return compact_review_json(snapshot, string_limit=string_limit, list_limit=list_limit)


def build_review_prompt(context: dict[str, Any]) -> str:
    prompt = ""
    for string_limit, list_limit in (
        (REVIEW_JSON_STRING_LIMIT, REVIEW_JSON_LIST_LIMIT),
        (8_000, 120),
        (2_000, 80),
        (800, 40),
        (300, 25),
    ):
        prompt = _build_review_prompt(
            context,
            string_limit=string_limit,
            list_limit=list_limit,
        )
        if len(prompt) <= REVIEW_PROMPT_CHAR_LIMIT:
            return prompt
    return prompt


def _build_review_prompt(
    context: dict[str, Any],
    *,
    string_limit: int,
    list_limit: int,
) -> str:
    submission = context.get("submission") if isinstance(context.get("submission"), dict) else {}
    submission_id = str(submission.get("id") or "")
    server_name = str(submission.get("name") or "")
    version = str(submission.get("version") or "")
    id_list = f"- {submission_id}" if submission_id else "- none"
    mcp_server_model = submitted_mcp_server_model_json(submission)
    submission_snapshot = (
        "\nWardn Hub submission JSON snapshot:\n"
        "```json\n"
        f"{json.dumps(submission_snapshot_for_review(submission, string_limit=string_limit, list_limit=list_limit), indent=2, sort_keys=True)}\n"
        "```\n"
    )
    server_model_snapshot = (
        "\nSubmitted MCP server model JSON from to_json_dict():\n"
        "```json\n"
        f"{json.dumps(compact_review_json(mcp_server_model, string_limit=string_limit, list_limit=list_limit), indent=2, sort_keys=True)}\n"
        "```\n"
    )

    return f"""Validate one Wardn Hub MCP server version that is currently in review.

{SYSTEM_REVIEW_INSTRUCTIONS}

Scope:
1. Validate only the in-review submission ID listed in the Submission context section below.
2. Use the Wardn Hub submission JSON snapshot for submission ID, status, validation result, and workflow fields.
3. Confirm the snapshot has status "submitted" and that its name/version match the Submission context section. In the Wardn Hub UI, this status is shown as "In review".
4. Ignore any other submissions or versions.
5. If the listed snapshot is not an in-review submission for this version, report that clearly and stop.

Validation workflow for each submission:
1. Read the Submitted MCP server model JSON from to_json_dict(), submission.validationResult, and the model _meta.sourceReview.
2. Identify the source repository from serverJson.repository.url and any source links in documentation/package metadata.
3. Read the upstream README and relevant docs/files needed to verify installation, package transport, environment variables, CLI arguments, prerequisites, capabilities, limitations, and version/package metadata.
4. Compare the source review evidence against the upstream source. Do not assume importer output is complete.
5. {REGISTRY_METADATA_SCOPE_RULE}
6. If submissionType is "new_server", serverJson.version is the Wardn registry version and must be "1.0.0". Do not reject a new-server submission because serverJson.version differs from an upstream package, image, CLI, npm, PyPI, or MCP registry version. Verify those upstream artifact versions against packages[].version, remotes metadata, documentation, or _meta evidence instead.

Required checks:
- Registry name, title, description, website, repository, version, icons, packages, remotes, and documentation are present and accurate where applicable.
- Registry namespace is derived from serverJson.name and is either io.github.owner/server or reverse-DNS domain/server. Verify serverJson._meta.registryNamespace evidence when present, especially official_registry, DNS, HTTP well-known, or GitHub ownership evidence.
- For official MCP registry imports, confirm registryNamespace.verificationStatus is "verified", verificationMethod is "official_registry", and evidenceUrl points to the official registry record.
- For io.github.* namespaces, compare the namespace owner against the linked GitHub repository owner unless official registry evidence already verifies the namespace.
- Package identifiers and versions are split correctly. No package identifier contains a version or tag.
- Transport command, args, env, and transport type match documented install/run instructions.
{VALIDATION_PACKAGE_ARGUMENT_CHECKS}
{VALIDATION_REMOTE_QUERY_PARAMETER_CHECKS}
- No environment value uses placeholder syntax that wraps names in dollar signs and braces.
- Environment variable names are unique within each package target and within sourceReview.environmentVariables.
- Secret or user-specific defaults are empty strings.
- Every documented environment variable is represented in sourceReview.environmentVariables, including optional variables that affect runtime, transport, auth, security, media/file access, tunnel mode, host/origin behavior, or feature flags.
- Variables required at launch are also represented in packages[].transport.env with safe defaults.
- CLI arguments and configurable flags are represented in sourceReview.commandArguments and packageArguments; only default launch args are represented in package transport args.
- Prerequisites are represented in sourceReview.prerequisites.
- sourceReview.filesRead, installCommands, commandArguments, environmentVariables, prerequisites, capabilitiesReviewed, limitationsReviewed, and unknowns are complete.
- capabilitiesReviewed and limitationsReviewed are true.
- sourceReview.unknowns is empty unless there is a specific documented reason.
- validationResult.status is "passed"; warning or failing checks mean the submission is not ready for approval until resolved.
- If submissionType is "new_server", serverJson.version must be "1.0.0"; upstream artifact versions belong in packages[].version, remotes metadata, documentation, or _meta evidence.

Report format:
- Submission ID
- Server name and version
- Repository/source files reviewed
- Findings grouped by severity
- Missing or incorrect environment variables
- Missing or incorrect command arguments
- Suggested rejection message if the submission should be rejected
- Suggested approval note if the submission passes
- Final section named exactly "Review result JSON" containing one fenced JSON object that validates against this schema:
```json
{REVIEW_DECISION_SCHEMA_JSON}
```

Decision rules:
- Use "pass" only when the submitted metadata can be verified against source evidence and validationResult.status is "passed".
- Use "needs_fixes" or "reject" only when the submitted metadata is clearly wrong or incomplete.
- If decision is "needs_fixes" or "reject", suggestedRejectionMessage must be a non-empty, user-facing message that explains the exact changes needed.
- Use "cannot validate" when source evidence is unavailable, ambiguous, or insufficient to make a safe approval/rejection decision. This leaves the submission unchanged so it can be retried or reviewed manually later.

After the report:
- Do not call Wardn Hub API endpoints.
- Do not approve, reject, publish, update, or delete anything directly.
- The database review controller will parse only the final Review result JSON for automatic actions. Markdown headings such as "Decision: pass" are ignored by automation.

Do not mark a submission as passing if source review evidence is incomplete, validationResult has warning or failing checks, upstream docs mention an env var/argument/prerequisite that is missing, or package transport details cannot be verified.

Submission context:
Server: {server_name}
Version: {version or "unknown"}
In-review submission ID shown in UI:
{id_list}
{submission_snapshot}
{server_model_snapshot}"""


def submission_label(submission: dict[str, Any]) -> str:
    name = submission.get("name") or "<unknown>"
    version = submission.get("version") or "<unknown>"
    submission_id = submission.get("id") or "<unknown>"
    return f"{name}@{version} ({submission_id})"


def next_submission_for_review(
    client: WardnHubDatabaseReviewClient,
    *,
    skipped_ids: set[str],
    submission_id: str | None,
) -> dict[str, Any] | None:
    next_submission = getattr(client, "next_submission", None)
    if callable(next_submission):
        return next_submission(
            skipped_ids=skipped_ids,
            submission_id=submission_id,
        )
    submissions = client.list_submissions()
    pending = pending_submissions(submissions, skipped_ids=skipped_ids)
    if submission_id:
        if submission_id in skipped_ids:
            return None
        return next(
            (submission for submission in pending if str(submission.get("id") or "") == submission_id),
            None,
        )

    return pending[0] if pending else None


def display_user(user: dict[str, Any]) -> str:
    display_name = user.get("display_name") or user.get("displayName") or ""
    email = user.get("email") or ""
    user_id = user.get("id") or ""
    label = display_name or email or str(user_id)
    roles = []
    if bool_field(user, "is_superuser", "isSuperuser"):
        roles.append("superuser")
    if bool_field(user, "is_global_moderator", "isGlobalModerator"):
        roles.append("moderator")
    if user.get("_wardnHubCanPublish"):
        roles.append("publish")
    role_text = ", ".join(roles) if roles else "no review role"
    return f"{label} [{role_text}]"


def print_heading(stdout: TextIO, label: str) -> None:
    print("\n" + "=" * 80, file=stdout)
    print(label, file=stdout)
    print("=" * 80, file=stdout)


def read_decision(stdin: TextIO, stdout: TextIO, *, can_publish: bool) -> str:
    choices = "approve [a], reject [r], skip [s], quit [q]"
    if can_publish:
        choices = "approve [a], approve+publish [p], reject [r], skip [s], quit [q]"

    while True:
        print(f"\nDecision ({choices}): ", end="", file=stdout, flush=True)
        value = stdin.readline()
        if not value:
            return "quit"
        normalized = value.strip().lower()
        if normalized in {"a", "approve"}:
            return "approve"
        if can_publish and normalized in {"p", "publish", "approve+publish", "approve_publish"}:
            return "approve_publish"
        if normalized in {"r", "reject"}:
            return "reject"
        if normalized in {"s", "skip"}:
            return "skip"
        if normalized in {"q", "quit", "exit"}:
            return "quit"
        print("Please choose one of the listed actions.", file=stdout)


def read_rejection_message(stdin: TextIO, stdout: TextIO) -> str:
    while True:
        print("Rejection message: ", end="", file=stdout, flush=True)
        message = stdin.readline()
        if not message:
            raise UserFacingError("rejection cancelled because no message was provided")
        message = message.strip()
        if 0 < len(message) <= 2000:
            return message
        print("Message must be between 1 and 2000 characters.", file=stdout)


def normalize_suggested_rejection_message(message: str) -> str | None:
    message = message.strip()
    if not message:
        return None
    lowered = message.lower().strip(".")
    if lowered in {"none", "n/a", "not applicable", "no rejection message"}:
        return None
    if len(message) > 2000:
        return message[:2000].rstrip()
    return message


def validation_blocking_messages(submission: dict[str, Any]) -> list[str]:
    messages = deterministic_submission_blocking_messages(submission)
    validation_result = submission.get("validationResult")
    if not isinstance(validation_result, dict):
        return messages

    status = str(validation_result.get("status") or "").lower()
    checks = validation_result.get("checks")
    validation_messages = [
        str(check.get("message") or "").strip()
        for check in checks
        if isinstance(check, dict)
        and str(check.get("status") or "").lower() in {"failed", "warning"}
        and str(check.get("message") or "").strip()
    ] if isinstance(checks, list) else []
    for message in validation_messages:
        if message not in messages:
            messages.append(message)
    if messages:
        return messages
    if status and status != "passed":
        return [f"validationResult.status is {status}."]
    return []


def deterministic_submission_blocking_messages(submission: dict[str, Any]) -> list[str]:
    submission_type = str(
        submission.get("submissionType") or submission.get("submission_type") or ""
    )
    server_json = submission.get("serverJson") or submission.get("server_json")
    server_version = (
        str(server_json.get("version") or "")
        if isinstance(server_json, dict)
        else ""
    )
    if submission_type == "new_server" and server_version != "1.0.0":
        return [NEW_SERVER_INITIAL_VERSION_MESSAGE]
    return []


def validation_rejection_message(messages: list[str]) -> str:
    details = "; ".join(messages)
    return (
        "Resolve Wardn validation issues before approval. "
        f"{details}"
    )


def extract_review_result(findings: str) -> ReviewDecisionPayload | None:
    label = re.search(
        r"(?im)^\s*(?:[-*]\s*)?(?:#+\s*)?(?:[*_`]+)?Review result JSON(?:[*_`]+)?\s*:?\s*$",
        findings,
    )
    if label is None:
        return None

    search_from = label.end()
    fenced = re.search(r"```(?:json)?\s*", findings[search_from:], re.IGNORECASE)
    if fenced is not None:
        payload_start = search_from + fenced.end()
    else:
        object_start = findings.find("{", search_from)
        if object_start < 0:
            return None
        payload_start = object_start

    try:
        payload, _end = json.JSONDecoder().raw_decode(findings, payload_start)
        return ReviewDecisionPayload.model_validate(payload)
    except (json.JSONDecodeError, ValidationError):
        return None


def apply_decision(
    client: WardnHubDatabaseReviewClient,
    submission_id: str,
    decision: str,
    *,
    dry_run: bool,
    stdin: TextIO,
    stdout: TextIO,
    suggested_rejection_message: str | None = None,
) -> None:
    if decision == "approve":
        if dry_run:
            print(f"Dry run: would approve {submission_id}.", file=stdout)
            return
        client.approve_submission(submission_id)
        print(f"Approved {submission_id}.", file=stdout)
        return

    if decision == "approve_publish":
        if dry_run:
            print(f"Dry run: would approve and publish {submission_id}.", file=stdout)
            return
        client.approve_submission(submission_id)
        client.publish_submission(submission_id)
        print(f"Approved and published {submission_id}.", file=stdout)
        return

    if decision == "reject":
        message = normalize_suggested_rejection_message(suggested_rejection_message or "")
        if message:
            print("Using suggested rejection message from LLM findings.", file=stdout)
        else:
            message = read_rejection_message(stdin, stdout)
        if dry_run:
            print(f"Dry run: would reject {submission_id} with: {message}", file=stdout)
            return
        client.reject_submission(submission_id, message)
        print(f"Rejected {submission_id}.", file=stdout)
        return

    raise UserFacingError(f"unknown decision: {decision}")


def review_loop(
    *,
    client: WardnHubDatabaseReviewClient,
    reviewer: Reviewer,
    user: dict[str, Any],
    max_reviews: int | None,
    once: bool,
    dry_run: bool,
    auto_reject: bool,
    auto_approve: bool,
    stdin: TextIO,
    stdout: TextIO,
    submission_id: str | None = None,
    non_interactive: bool = False,
    auto_publish: bool = False,
) -> int:
    skipped_ids: set[str] = set()
    completed_reviews = 0
    review_errors = 0
    can_publish = bool(user.get("_wardnHubCanPublish"))

    while True:
        submission = next_submission_for_review(
            client,
            skipped_ids=skipped_ids,
            submission_id=submission_id,
        )
        if submission is None:
            if submission_id:
                print(
                    f"Submission {submission_id} is not currently submitted for review.",
                    file=stdout,
                )
            else:
                print("No submitted MCP server submissions remain for this run.", file=stdout)
            return 1 if review_errors else 0

        current_submission_id = str(submission["id"])
        print_heading(stdout, f"Reviewing {submission_label(submission)}")
        context = build_review_context(client, submission)
        prompt = build_review_prompt(context)
        environment = {
            "WARDN_HUB_REVIEW_SUBMISSION_ID": current_submission_id,
        }

        try:
            findings = reviewer.review(prompt, environment=environment)
        except UserFacingError as exc:
            review_errors += 1
            completed_reviews += 1
            skipped_ids.add(current_submission_id)
            print(
                f"Review failed for {current_submission_id}; leaving submission unchanged: {exc}",
                file=stdout,
            )
            if once or (max_reviews is not None and completed_reviews >= max_reviews):
                print("Review limit reached.", file=stdout)
                return 1
            continue
        print_heading(stdout, "LLM Findings")
        print(findings, file=stdout)

        review_result = extract_review_result(findings)
        suggested_rejection_message = (
            normalize_suggested_rejection_message(review_result.suggested_rejection_message or "")
            if review_result is not None
            else None
        )
        review_submission = (
            context.get("submission")
            if isinstance(context.get("submission"), dict)
            else submission
        )
        validation_messages = validation_blocking_messages(review_submission)
        if review_result is None:
            completed_reviews += 1
            skipped_ids.add(current_submission_id)
            print(
                f"No valid Review result JSON was returned for {current_submission_id}; "
                "leaving submission unchanged and skipping it for this run.",
                file=stdout,
            )
            if once or (max_reviews is not None and completed_reviews >= max_reviews):
                print("Review limit reached.", file=stdout)
                return 1 if review_errors else 0
            continue

        if review_result is not None and review_result.decision in {"cannot_validate", "skip"}:
            completed_reviews += 1
            skipped_ids.add(current_submission_id)
            print(
                f"Reviewer could not determine a safe action for {current_submission_id}; "
                "leaving submission unchanged and skipping it for this run.",
                file=stdout,
            )
            if once or (max_reviews is not None and completed_reviews >= max_reviews):
                print("Review limit reached.", file=stdout)
                return 1 if review_errors else 0
            continue

        if review_result is not None and review_result.decision == "pass" and validation_messages:
            validation_message = validation_rejection_message(validation_messages)
            if auto_reject:
                print(
                    "LLM returned pass, but Wardn validation says the submission is not ready; "
                    "auto-rejecting with validation messages.",
                    file=stdout,
                )
                completed_reviews += 1
                try:
                    apply_decision(
                        client,
                        current_submission_id,
                        "reject",
                        dry_run=dry_run,
                        stdin=stdin,
                        stdout=stdout,
                        suggested_rejection_message=validation_message,
                    )
                except UserFacingError as exc:
                    review_errors += 1
                    skipped_ids.add(current_submission_id)
                    print(
                        f"Action failed for {current_submission_id}; skipping it for this run: {exc}",
                        file=stdout,
                    )
                if once or (max_reviews is not None and completed_reviews >= max_reviews):
                    print("Review limit reached.", file=stdout)
                    return 1 if review_errors else 0
                continue

            print(
                "LLM returned pass, but Wardn validation says the submission is not ready: "
                f"{'; '.join(validation_messages)} "
                + (
                    "Leaving submission unchanged and skipping it for this run."
                    if non_interactive
                    else "Leaving this submission for manual decision."
                ),
                file=stdout,
            )
            if non_interactive:
                completed_reviews += 1
                skipped_ids.add(current_submission_id)
                if once or (max_reviews is not None and completed_reviews >= max_reviews):
                    print("Review limit reached.", file=stdout)
                    return 1 if review_errors else 0
                continue

        if (
            auto_reject
            and review_result is not None
            and review_result.decision in {"needs_fixes", "reject"}
        ):
            if suggested_rejection_message:
                print(
                    "Auto-rejecting with suggested rejection message from LLM findings.",
                    file=stdout,
                )
                completed_reviews += 1
                try:
                    apply_decision(
                        client,
                        current_submission_id,
                        "reject",
                        dry_run=dry_run,
                        stdin=stdin,
                        stdout=stdout,
                        suggested_rejection_message=suggested_rejection_message,
                    )
                except UserFacingError as exc:
                    review_errors += 1
                    skipped_ids.add(current_submission_id)
                    print(
                        f"Action failed for {current_submission_id}; skipping it for this run: {exc}",
                        file=stdout,
                    )
                if once or (max_reviews is not None and completed_reviews >= max_reviews):
                    print("Review limit reached.", file=stdout)
                    return 1 if review_errors else 0
                continue

            print(
                "Auto-reject requested, but no suggested rejection message was found; "
                + (
                    "leaving submission unchanged and skipping it for this run."
                    if non_interactive
                    else "leaving this submission for manual decision."
                ),
                file=stdout,
            )
            if non_interactive:
                completed_reviews += 1
                skipped_ids.add(current_submission_id)
                if once or (max_reviews is not None and completed_reviews >= max_reviews):
                    print("Review limit reached.", file=stdout)
                    return 1 if review_errors else 0
                continue

        if auto_publish and review_result is not None and review_result.decision == "pass":
            if can_publish:
                print("Auto-publishing LLM pass decision.", file=stdout)
                completed_reviews += 1
                try:
                    apply_decision(
                        client,
                        current_submission_id,
                        "approve_publish",
                        dry_run=dry_run,
                        stdin=stdin,
                        stdout=stdout,
                        suggested_rejection_message=suggested_rejection_message,
                    )
                except UserFacingError as exc:
                    review_errors += 1
                    skipped_ids.add(current_submission_id)
                    print(
                        f"Action failed for {current_submission_id}; skipping it for this run: {exc}",
                        file=stdout,
                    )
                if once or (max_reviews is not None and completed_reviews >= max_reviews):
                    print("Review limit reached.", file=stdout)
                    return 1 if review_errors else 0
                continue

            print(
                "Auto-publish requested, but the authenticated token does not have publish "
                + (
                    f"access; leaving {current_submission_id} unchanged and skipping it "
                    "for this run."
                    if non_interactive
                    else "access; leaving this submission for manual decision."
                ),
                file=stdout,
            )
            if non_interactive:
                completed_reviews += 1
                skipped_ids.add(current_submission_id)
                if once or (max_reviews is not None and completed_reviews >= max_reviews):
                    print("Review limit reached.", file=stdout)
                    return 1 if review_errors else 0
                continue

        if (
            auto_approve
            and not auto_publish
            and review_result is not None
            and review_result.decision == "pass"
        ):
            print("Auto-approving LLM pass decision.", file=stdout)
            completed_reviews += 1
            try:
                apply_decision(
                    client,
                    current_submission_id,
                    "approve",
                    dry_run=dry_run,
                    stdin=stdin,
                    stdout=stdout,
                    suggested_rejection_message=suggested_rejection_message,
                )
            except UserFacingError as exc:
                review_errors += 1
                skipped_ids.add(current_submission_id)
                print(
                    f"Action failed for {current_submission_id}; skipping it for this run: {exc}",
                    file=stdout,
                )
            if once or (max_reviews is not None and completed_reviews >= max_reviews):
                print("Review limit reached.", file=stdout)
                return 1 if review_errors else 0
            continue

        if non_interactive:
            completed_reviews += 1
            skipped_ids.add(current_submission_id)
            print(
                f"No automatic action was safe for {current_submission_id}; "
                "leaving submission unchanged and skipping it for this run.",
                file=stdout,
            )
            if once or (max_reviews is not None and completed_reviews >= max_reviews):
                print("Review limit reached.", file=stdout)
                return 1 if review_errors else 0
            continue

        decision = read_decision(stdin, stdout, can_publish=can_publish)
        if decision == "quit":
            print("Stopping review loop.", file=stdout)
            return 1 if review_errors else 0
        if decision == "skip":
            skipped_ids.add(current_submission_id)
            print(f"Skipped {current_submission_id} for this run.", file=stdout)
        else:
            try:
                apply_decision(
                    client,
                    current_submission_id,
                    decision,
                    dry_run=dry_run,
                    stdin=stdin,
                    stdout=stdout,
                    suggested_rejection_message=suggested_rejection_message,
                )
            except UserFacingError as exc:
                review_errors += 1
                skipped_ids.add(current_submission_id)
                print(
                    f"Action failed for {current_submission_id}; skipping it for this run: {exc}",
                    file=stdout,
                )

        completed_reviews += 1
        if once or (max_reviews is not None and completed_reviews >= max_reviews):
            print("Review limit reached.", file=stdout)
            return 1 if review_errors else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Review submitted Wardn Hub MCP server submissions with an LLM, then apply "
            "human-selected moderation actions."
        )
    )
    parser.add_argument(
        "--codex-app-server-url",
        default=os.getenv(CODEX_APP_SERVER_URL_ENV, ""),
        help=(
            "Experimental Codex app-server WebSocket URL for review, for example "
            f"ws://127.0.0.1:41237. Defaults to ${CODEX_APP_SERVER_URL_ENV}."
        ),
    )
    parser.add_argument(
        "--review-timeout",
        type=int,
        default=900,
        help="Seconds to wait for each Codex app-server review.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show Codex app-server reviewer output while it is produced.",
    )
    parser.add_argument(
        "--max-reviews",
        type=int,
        default=None,
        help="Maximum number of submissions to review in this run.",
    )
    parser.add_argument(
        "--submission-id",
        default="",
        help="Review exactly one submitted submission ID.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Review one submitted submission and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run LLM review and prompts without mutating submissions.",
    )
    parser.add_argument(
        "--auto-reject",
        action="store_true",
        help=(
            "Automatically reject reviews whose LLM decision is needs fixes or reject, using "
            "the suggested rejection message. Cannot-validate decisions are skipped."
        ),
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help=(
            "Automatically approve reviews whose LLM decision is pass. This never publishes "
            "submissions."
        ),
    )
    parser.add_argument(
        "--auto-publish",
        action="store_true",
        help=(
            "Automatically approve and publish reviews whose LLM decision is pass."
        ),
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help=(
            "Never prompt for a decision. If no configured automatic action is safe, leave the "
            "submission unchanged and skip it for this run."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        codex_app_server_url = str(args.codex_app_server_url or "").strip()
        if not codex_app_server_url:
            raise UserFacingError(
                "Codex app-server review is required. Set "
                f"{CODEX_APP_SERVER_URL_ENV} or pass --codex-app-server-url."
            )

        client = WardnHubDatabaseReviewClient()
        user = validate_database_review_client(client)
        reviewer: Reviewer = CodexAppServerReviewer(
            url=codex_app_server_url,
            timeout_seconds=args.review_timeout,
            cwd=None,
            progress_stream=sys.stdout if args.verbose else None,
            stream_output=args.verbose,
            auth_token=os.getenv(CODEX_APP_SERVER_AUTH_TOKEN_ENV, "").strip(),
        )
        print(f"Authenticated as {display_user(user)}.", file=sys.stdout)
        return review_loop(
            client=client,
            reviewer=reviewer,
            user=user,
            max_reviews=args.max_reviews,
            once=args.once,
            dry_run=args.dry_run,
            auto_reject=args.auto_reject,
            auto_approve=args.auto_approve,
            auto_publish=args.auto_publish,
            stdin=sys.stdin,
            stdout=sys.stdout,
            submission_id=args.submission_id.strip() or None,
            non_interactive=args.non_interactive,
        )
    except UserFacingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
