# ruff: noqa: E501

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO

from app.cli.review_pending_submissions import (
    CODEX_APP_SERVER_URL_ENV,
    REGISTRY_METADATA_SCOPE_RULE,
    VALIDATION_PACKAGE_ARGUMENT_CHECKS,
    VALIDATION_REMOTE_QUERY_PARAMETER_CHECKS,
    CodexAppServerReviewer,
    UserFacingError,
    display_user,
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

        return self._loop.run_until_complete(run())

    def list_submissions(self) -> list[dict[str, Any]]:
        async def operation(session: Any) -> list[dict[str, Any]]:
            from app.modules.submissions.service import list_submissions_for_system_fix

            submissions = await list_submissions_for_system_fix(session)
            return [submission_read_to_review_dict(submission) for submission in submissions]

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
                raise UserFacingError(f"Updated serverJson is invalid: {exc}") from exc
            submission = await fix_submission_by_system(
                session,
                uuid.UUID(submission_id),
                payload,
            )
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
```

System fix mode:
- Use the submission JSON snapshot and submitted MCP server model JSON in this prompt as the Wardn Hub source of truth.
- Do not call Wardn Hub API endpoints.
- Do not request, infer, or expose Wardn Hub credentials.
- Review upstream public source repositories, README files, documentation, and package metadata only.
- The database fix controller will apply your returned serverJson if it is valid and ready for review.

Eligibility:
- This worker only receives draft/rejected submissions owned by a superuser or active partner organization.
- If the snapshot is not status "draft" or "rejected", return Decision: cannot fix.

Goal:
- Validate the submission against any submit/review feedback and Wardn Hub review requirements.
- Read the upstream source/docs needed to fix missing or incomplete metadata.
- Return a complete replacement serverJson object.
- Do not approve, reject, publish, withdraw, delete, or otherwise moderate this submission.
- Do not create a new submission.
- Do not guess source-review evidence. It must reflect URLs/files actually inspected.
- If the submission lacks enough source links to verify the server, return Decision: cannot fix and state the official repository or documentation URL needed from the user.
- {REGISTRY_METADATA_SCOPE_RULE}

Source review requirements:
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
- Decision: fixed or cannot fix
- Summary
- Source URLs/files read
- Updated serverJson:
```json
{{}}
```

If you cannot fix it, omit Updated serverJson and include the exact missing information needed from the user."""


def extract_updated_server_json(findings: str) -> dict[str, Any] | None:
    label = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:#+\s*)?Updated serverJson\s*:?\s*$", findings)
    search_from = label.end() if label is not None else 0
    fenced = re.search(r"```(?:json)?\s*(?P<payload>.*?)```", findings[search_from:], re.DOTALL)
    if fenced is None and label is None:
        fenced = re.search(r"```(?:json)?\s*(?P<payload>.*?)```", findings, re.DOTALL)
    if fenced is None:
        return None
    try:
        payload = json.loads(fenced.group("payload"))
    except json.JSONDecodeError as exc:
        raise UserFacingError(f"LLM returned invalid Updated serverJson JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise UserFacingError("LLM returned Updated serverJson that is not a JSON object")
    return payload


def should_skip_fix(findings: str) -> bool:
    match = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:#+\s*)?Decision\s*:\s*(.+?)\s*$", findings)
    if match is None:
        return False
    decision = re.sub(r"[`*_]", "", match.group(1)).strip().lower()
    return decision.startswith("cannot fix") or decision.startswith("skip")


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
                if should_skip_fix(findings):
                    stats.skipped += 1
                    skipped_ids.add(current_submission_id)
                    print(f"Reviewer could not fix {current_submission_id}; leaving unchanged.", file=stdout)
                else:
                    updated_server_json = extract_updated_server_json(findings)
                    if updated_server_json is None:
                        raise UserFacingError("LLM did not return Updated serverJson")
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
            cwd=Path.cwd(),
            progress_stream=sys.stdout if args.verbose else None,
            stream_output=args.verbose,
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
