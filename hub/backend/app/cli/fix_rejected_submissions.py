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
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TextIO

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.cli.review_pending_submissions import (
    CODEX_APP_SERVER_AUTH_TOKEN_ENV,
    CODEX_APP_SERVER_URL_ENV,
    REGISTRY_METADATA_SCOPE_RULE,
    VALIDATION_PACKAGE_ARGUMENT_CHECKS,
    VALIDATION_REMOTE_QUERY_PARAMETER_CHECKS,
    CodexAppServerReviewer,
    UserFacingError,
    display_user,
    is_transient_database_disconnect,
    print_heading,
    submission_label,
    submission_read_to_review_dict,
    submitted_mcp_server_model_json,
)
from app.modules.registry.schemas import RegistryServerVersionCreate

SOURCE_REVIEW_LIST_FORMAT = """Source review list format:
- filesRead, installCommands, commandArguments, and prerequisites must be readable strings or objects with at least one of: flag, name, value, default, description.
- Do not put arbitrary nested objects in commandArguments. For CLI options, prefer strings such as "--stdio" or objects like {"flag":"--port","requiresValue":true,"description":"Port for HTTP transport."}.
- Do not write LLM-generated review evidence into flat sourceReview fields; use sourceReview.llm so it is distinguishable from human review evidence."""

DRAFT_METADATA_RULES = f"""Metadata rules:
- Do not use environment placeholder values that wrap names in dollar signs and braces.
- For secrets or user-specific values, use an empty string.
- Do not create duplicate environment variable entries. If the same variable appears in multiple docs/import sources, merge it into one entry with the best description, default, required, secret, and source evidence.
- Split package versions from identifiers. Do not put versions or tags inside package identifiers.
- Ensure package transport command, args, env, and type match documented install/run instructions.
{VALIDATION_PACKAGE_ARGUMENT_CHECKS}
{VALIDATION_REMOTE_QUERY_PARAMETER_CHECKS}
- Ensure documentation, title, description, websiteUrl, repository, packages/remotes, icons, and version are accurate where available."""

REPAIRABLE_STATUSES = {"draft", "rejected"}


class FixDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    decision: Literal["fixed", "cannot_fix", "skip"]
    updated_server_json: dict[str, Any] | None = Field(
        default=None,
        alias="updatedServerJson",
    )
    summary: str = Field(default="", max_length=2000)
    source_files_read: list[str] = Field(default_factory=list, alias="sourceFilesRead")
    missing_information: list[str] = Field(default_factory=list, alias="missingInformation")

    @model_validator(mode="after")
    def require_updated_server_json_for_fixed(self) -> FixDecisionPayload:
        if self.decision == "fixed" and self.updated_server_json is None:
            raise ValueError("updatedServerJson is required when decision is fixed")
        return self


FIX_DECISION_SCHEMA_JSON = json.dumps(
    FixDecisionPayload.model_json_schema(by_alias=True),
    indent=2,
    sort_keys=True,
)


class FixClient(Protocol):
    def list_submissions(self) -> list[dict[str, Any]]: ...

    def get_submission(self, submission_id: str) -> dict[str, Any]: ...

    def fix_submission(self, submission_id: str, server_json: dict[str, Any]) -> dict[str, Any]: ...


class Reviewer(Protocol):
    def review(self, prompt: str, *, environment: dict[str, str]) -> str: ...


class WardnHubDatabaseFixClient:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()

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
            from app.modules.submissions.service import list_submissions_for_system_fix

            submissions = await list_submissions_for_system_fix(session)
            return [submission_read_to_review_dict(submission) for submission in submissions]

        return self._run_database_operation(operation)

    def next_submission(
        self,
        *,
        skipped_ids: set[str],
        submission_id: str | None,
    ) -> dict[str, Any] | None:
        async def operation(session: Any) -> dict[str, Any] | None:
            from app.modules.submissions.service import next_submission_for_system_fix

            submission = await next_submission_for_system_fix(
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

    def fix_submission(self, submission_id: str, server_json: dict[str, Any]) -> dict[str, Any]:
        async def operation(session: Any) -> dict[str, Any]:
            from app.modules.submissions.service import fix_submission_by_system

            try:
                payload = RegistryServerVersionCreate.model_validate(server_json)
            except ValueError as exc:
                raise UserFacingError(f"updatedServerJson is invalid: {exc}") from exc
            try:
                submission = await fix_submission_by_system(
                    session,
                    uuid.UUID(submission_id),
                    payload,
                )
            except Exception as exc:
                from app.modules.submissions.exceptions import SubmissionError

                if isinstance(exc, SubmissionError):
                    raise UserFacingError(f"Unable to apply updated serverJson: {exc}") from exc
                raise
            return submission_read_to_review_dict(submission)

        return self._run_database_operation(operation, commit=True)


@dataclass
class FixStats:
    seen: int = 0
    candidate: int = 0
    fixed: int = 0
    skipped: int = 0
    failed: int = 0


def validate_database_fix_client(client: FixClient) -> dict[str, Any]:
    next_submission = getattr(client, "next_submission", None)
    if callable(next_submission):
        next_submission(skipped_ids=set(), submission_id=None)
    else:
        client.list_submissions()
    return {
        "id": "database",
        "display_name": "Wardn Hub system fix",
        "email": "",
        "is_active": True,
        "is_superuser": True,
        "is_global_moderator": False,
        "is_database_fix": True,
    }


def repairable_submissions(
    submissions: Iterable[dict[str, Any]],
    *,
    skipped_ids: set[str],
) -> list[dict[str, Any]]:
    repairable = [
        submission
        for submission in submissions
        if submission.get("status") in REPAIRABLE_STATUSES
        and str(submission.get("id") or "") not in skipped_ids
    ]
    indexed_repairable = list(enumerate(repairable))
    indexed_repairable.sort(key=lambda item: (submission_queue_timestamp(item[1]), item[0]))
    return [submission for _, submission in indexed_repairable]


def submission_queue_timestamp(submission: dict[str, Any]) -> str:
    for field in ("updatedAt", "updated_at", "createdAt", "created_at", "submittedAt", "submitted_at"):
        value = submission.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "9999-12-31T23:59:59.999999Z"


def next_submission_to_fix(
    client: FixClient,
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
    repairable = repairable_submissions(submissions, skipped_ids=skipped_ids)
    if submission_id:
        if submission_id in skipped_ids:
            return None
        return next(
            (submission for submission in repairable if str(submission.get("id") or "") == submission_id),
            None,
        )
    return repairable[0] if repairable else None


def build_fix_context(client: FixClient, submission: dict[str, Any]) -> dict[str, Any]:
    submission_id = str(submission["id"])
    fresh_submission = client.get_submission(submission_id)
    return {
        "submission": fresh_submission,
    }


def build_fix_prompt(context: dict[str, Any]) -> str:
    submission = context.get("submission") if isinstance(context.get("submission"), dict) else {}
    submission_id = str(submission.get("id") or "")
    server_name = str(submission.get("name") or "")
    version = str(submission.get("version") or "")
    rejection_message = str(
        submission.get("rejectionMessage") or submission.get("rejection_message") or "unknown"
    )
    status = str(submission.get("status") or "unknown")
    mcp_server_model = submitted_mcp_server_model_json(submission)
    submission_snapshot = json.dumps(submission, indent=2, sort_keys=True)
    server_model_snapshot = json.dumps(mcp_server_model, indent=2, sort_keys=True)

    return f"""Fix this Wardn Hub draft or rejected MCP server submission so it can be submitted for review.

System fix mode:
- Use the submission JSON snapshot and submitted MCP server model JSON in this prompt as the Wardn Hub source of truth.
- Do not call Wardn Hub API endpoints.
- Do not request, infer, or expose Wardn Hub credentials.
- Review upstream public source repositories, README files, documentation, and package metadata only.
- The database fix controller will apply your returned serverJson if it is valid and ready for review.

Eligibility:
- This worker only receives draft/rejected submissions owned by a superuser or active partner organization.
- If the snapshot is not status "draft" or "rejected", return Fix result JSON with decision "cannot_fix".

Goal:
- Validate the submission against any submit/review feedback and Wardn Hub review requirements.
- Read the upstream source/docs needed to fix missing or incomplete metadata.
- Return a complete replacement serverJson object.
- Do not approve, reject, publish, withdraw, delete, or otherwise moderate this submission.
- Do not create a new submission.
- Do not guess source-review evidence. It must reflect URLs/files actually inspected.
- If the submission lacks enough source links to verify the server, return Fix result JSON with decision "cannot_fix" and list the official repository or documentation URL needed from the user in missingInformation.
- {REGISTRY_METADATA_SCOPE_RULE}
- If submissionType is "new_server", keep serverJson.version as the Wardn registry version from the submission snapshot, normally "1.0.0". Put upstream package, image, CLI, npm, PyPI, or MCP registry versions only in packages[].version, remotes metadata, documentation, or _meta evidence.

Source review requirements:
- Derive the registry namespace from serverJson.name. If the source is the official MCP registry, set serverJson._meta.registryNamespace with namespace, type, authority, verificationStatus "verified", verificationMethod "official_registry", evidenceUrl, and source "modelcontextprotocol-registry".
- For io.github.* names without official registry evidence, compare the namespace owner against the linked GitHub repository owner and record any uncertainty in sourceReview.llm.unknowns.
- Fill serverJson._meta.sourceReview.llm.filesRead with every README/docs/source URL or file inspected.
- Fill sourceReview.llm.installCommands with documented install/run commands when package targets exist.
- Fill sourceReview.llm.commandArguments with documented CLI args/configurable flags.
- Fill sourceReview.llm.environmentVariables with every documented environment variable, including optional variables that affect runtime, transport, auth, security, media/file access, tunnel mode, host/origin behavior, or feature flags.
- Fill sourceReview.llm.prerequisites with required local apps, services, accounts, API keys, browser/runtime dependencies, or external services.
- Set sourceReview.llm.capabilitiesReviewed = true after reviewing documented capabilities/tools/features.
- Set sourceReview.llm.limitationsReviewed = true after reviewing documented limitations, caveats, unsupported behavior, risks, or operational requirements.
- Set sourceReview.llm.unknowns = [] only when all required source-review questions are resolved. Otherwise list specific unknowns and do not submit.

{SOURCE_REVIEW_LIST_FORMAT}

{DRAFT_METADATA_RULES}

Return format:
- Summary
- Source URLs/files read
- Final section named exactly "Fix result JSON" containing one fenced JSON object that validates against this schema:
```json
{FIX_DECISION_SCHEMA_JSON}
```

If you cannot fix it, set decision to "cannot_fix", set updatedServerJson to null, and include the exact missing information needed from the user in missingInformation.
The database fix controller will parse only the final Fix result JSON for automatic actions. Markdown headings such as "Decision: fixed" and "Updated serverJson" are ignored by automation.

Submission context:
Submission ID: {submission_id}
Server name: {server_name or "unknown"}
Version: {version or "unknown"}
Current status: {status}
Current submit/review feedback: {rejection_message or "unknown"}

Wardn Hub submission JSON snapshot:
```json
{submission_snapshot}
```

Submitted MCP server model JSON from to_json_dict():
```json
{server_model_snapshot}
```"""


def extract_fix_result(findings: str) -> FixDecisionPayload | None:
    label = re.search(
        r"(?im)^\s*(?:[-*]\s*)?(?:#+\s*)?(?:[*_`]+)?Fix result JSON(?:[*_`]+)?\s*:?\s*$",
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
        return FixDecisionPayload.model_validate(payload)
    except (json.JSONDecodeError, ValidationError):
        return None


def normalize_updated_server_json(
    server_json: dict[str, Any],
    submission: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(server_json)
    submission_type = str(submission.get("submissionType") or submission.get("submission_type") or "")
    if submission_type == "new_server":
        submission_version = str(submission.get("version") or "").strip() or "1.0.0"
        normalized["version"] = submission_version
    return normalized


def fix_loop(
    *,
    client: FixClient,
    reviewer: Reviewer,
    user: dict[str, Any],
    max_fixes: int | None,
    once: bool,
    dry_run: bool,
    stdout: TextIO,
    submission_id: str | None = None,
) -> int:
    del user
    skipped_ids: set[str] = set()
    stats = FixStats()

    while True:
        submission = next_submission_to_fix(
            client,
            skipped_ids=skipped_ids,
            submission_id=submission_id,
        )
        if submission is None:
            if submission_id:
                print(
                    f"No eligible draft or rejected superuser/partner submission found for {submission_id}.",
                    file=stdout,
                )
            else:
                print("No eligible draft or rejected superuser/partner submissions remain.", file=stdout)
            print_stats(stats, stdout)
            return 1 if stats.failed else 0

        stats.seen += 1
        stats.candidate += 1
        current_submission_id = str(submission["id"])
        print_heading(stdout, f"Fixing {submission_label(submission)}")
        context = build_fix_context(client, submission)
        prompt = build_fix_prompt(context)

        if dry_run:
            print(prompt, file=stdout)
            stats.skipped += 1
            skipped_ids.add(current_submission_id)
        else:
            environment = os.environ.copy()
            environment["WARDN_HUB_FIX_SUBMISSION_ID"] = current_submission_id
            try:
                findings = reviewer.review(prompt, environment=environment)
                print_heading(stdout, "LLM Fix Output")
                print(findings, file=stdout)
                fix_result = extract_fix_result(findings)
                if fix_result is None:
                    raise UserFacingError("LLM did not return valid Fix result JSON")
                if fix_result.decision in {"cannot_fix", "skip"}:
                    stats.skipped += 1
                    skipped_ids.add(current_submission_id)
                    print(f"Reviewer could not fix {current_submission_id}; leaving unchanged.", file=stdout)
                else:
                    updated_server_json = fix_result.updated_server_json
                    if updated_server_json is None:
                        raise UserFacingError("Fix result JSON did not include updatedServerJson")
                    updated_server_json = normalize_updated_server_json(
                        updated_server_json,
                        context["submission"],
                    )
                    final_submission = client.fix_submission(
                        current_submission_id,
                        updated_server_json,
                    )
                    final_status = str(final_submission.get("status") or "")
                    if final_status == "submitted":
                        stats.fixed += 1
                        print(f"Submitted {current_submission_id} for review.", file=stdout)
                    else:
                        raise UserFacingError(
                            f"fix did not submit {current_submission_id}; final status is {final_status or '<unknown>'}"
                        )
            except UserFacingError as exc:
                stats.failed += 1
                skipped_ids.add(current_submission_id)
                print(
                    f"Fix failed for {current_submission_id}; leaving submission unchanged: {exc}",
                    file=stdout,
                )

        completed = stats.fixed + stats.failed + stats.skipped
        if once or (max_fixes is not None and completed >= max_fixes):
            print("Fix limit reached.", file=stdout)
            print_stats(stats, stdout)
            return 1 if stats.failed else 0


def print_stats(stats: FixStats, stdout: TextIO) -> None:
    print(
        "submission fixes: "
        f"seen={stats.seen} candidate={stats.candidate} fixed={stats.fixed} "
        f"skipped={stats.skipped} failed={stats.failed}",
        file=stdout,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fix draft or rejected Wardn Hub MCP server submissions owned by superusers or "
            "active partner organizations, then submit them for review."
        )
    )
    parser.add_argument(
        "--codex-app-server-url",
        default=os.getenv(CODEX_APP_SERVER_URL_ENV, ""),
        help=(
            "Experimental Codex app-server WebSocket URL for fixes, for example "
            f"ws://127.0.0.1:41237. Defaults to ${CODEX_APP_SERVER_URL_ENV}."
        ),
    )
    parser.add_argument(
        "--review-timeout",
        type=int,
        default=900,
        help="Seconds to wait for each Codex app-server fix.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show Codex app-server reviewer output while it is produced.",
    )
    parser.add_argument(
        "--max-fixes",
        type=int,
        default=None,
        help="Maximum number of submissions to fix in this run.",
    )
    parser.add_argument(
        "--submission-id",
        default="",
        help="Fix exactly one eligible draft or rejected submission ID.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Fix one eligible draft or rejected submission and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated fix prompt without mutating submissions or running Codex.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        codex_app_server_url = str(args.codex_app_server_url or "").strip()
        if not codex_app_server_url:
            raise UserFacingError(
                "Codex app-server fix is required. Set "
                f"{CODEX_APP_SERVER_URL_ENV} or pass --codex-app-server-url."
            )

        client = WardnHubDatabaseFixClient()
        user = validate_database_fix_client(client)
        reviewer: Reviewer = CodexAppServerReviewer(
            url=codex_app_server_url,
            timeout_seconds=args.review_timeout,
            cwd=None,
            progress_stream=sys.stdout if args.verbose else None,
            stream_output=args.verbose,
            auth_token=os.getenv(CODEX_APP_SERVER_AUTH_TOKEN_ENV, "").strip(),
            web_research_only=True,
        )
        print(f"Authenticated as {display_user(user)}.", file=sys.stdout)
        return fix_loop(
            client=client,
            reviewer=reviewer,
            user=user,
            max_fixes=args.max_fixes,
            once=args.once,
            dry_run=args.dry_run,
            stdout=sys.stdout,
            submission_id=args.submission_id.strip() or None,
        )
    except UserFacingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
