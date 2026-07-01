# ruff: noqa: E501

from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO

from app.cli.review_pending_submissions import (
    API_ACCESS_INSTRUCTIONS,
    API_BASE_URL_ENV,
    DEFAULT_API_BASE_URL,
    DEFAULT_REVIEW_COMMAND,
    DEFAULT_USER_AGENT,
    REGISTRY_METADATA_SCOPE_RULE,
    REVIEW_COMMAND_ENV,
    REVIEW_MODEL_ENV,
    REVIEW_PROGRESS_INTERVAL_ENV,
    REVIEW_THINKING_ENV,
    THINKING_LEVELS,
    TOKEN_ENV,
    USER_AGENT_ENV,
    HubApiError,
    SubprocessReviewer,
    UserFacingError,
    WardnHubApiClient,
    bool_field,
    display_user,
    ensure_codex_login,
    int_from_env,
    parse_review_command,
    print_heading,
    submission_label,
)

SOURCE_REVIEW_LIST_FORMAT = """Source review list format:
- filesRead, installCommands, commandArguments, and prerequisites must be readable strings or objects with at least one of: flag, name, value, default, description.
- Do not put arbitrary nested objects in commandArguments. For CLI options, prefer strings such as "--stdio" or objects like {"flag":"--port","requiresValue":true,"description":"Port for HTTP transport."}.
- Do not write LLM-generated review evidence into flat sourceReview fields; use sourceReview.llm so it is distinguishable from human review evidence."""

PACKAGE_ARGUMENT_RULES = """Package argument rules:
- packages[].transport.args must be the runnable default launch arguments only. Do not add every documented CLI option there.
- Add only arguments that must always be present for the documented default launch to packages[].transport.args, preserving order exactly.
- Optional CLI flags/configurable arguments belong in packages[].packageArguments with includeInLaunch false.
- Use packageArguments[].requiresValue true when a flag takes a user-supplied value. Do not include placeholder text like <port> or [url] in transport.args.
- requiresValue is a boolean. Do not set packageArguments[].value to placeholder examples such as "<host>", "[url]", "host", or "url".
- Do not include placeholders inside packageArguments[].flag. For docs that show "--host <host>", use {"flag":"--host","requiresValue":true,"includeInLaunch":false}.
- If a package argument is part of the default launch command, set includeInLaunch true. Otherwise leave it false.
- For package-manager launches, identifier is the package/image. packageArguments must describe only arguments passed to the server process after the package/image, never wrapper tokens such as npx/npm/uvx/pipx/docker, -y/--yes, run, --rm, -i, -p/--publish, -e/--env, volumes, networks, or the package/image identifier itself."""

REMOTE_QUERY_PARAMETER_RULES = """Remote query parameter rules:
- Remote endpoint URLs must be the base endpoint path only, without configurable query strings.
- Put remote query parameters in remotes[].queryParameters with name, description, isRequired, and isSecret.
- Do not put query parameters under remotes[].authentication.queryParameters.
- For docs that show "https://example.com/mcp?apiKey={apiKey}", use {"url":"https://example.com/mcp","queryParameters":[{"name":"apiKey","isRequired":true,"isSecret":true}]}. """

DRAFT_METADATA_RULES = f"""Metadata rules:
- Do not use environment placeholder values that wrap names in dollar signs and braces.
- For secrets or user-specific values, use an empty string.
- Do not create duplicate environment variable entries. If the same variable appears in multiple docs/import sources, merge it into one entry with the best description, default, required, secret, and source evidence.
- Split package versions from identifiers. Do not put versions or tags inside package identifiers.
- Ensure package transport command, args, env, and type match documented install/run instructions.
{PACKAGE_ARGUMENT_RULES}
{REMOTE_QUERY_PARAMETER_RULES}
- Ensure documentation, title, description, websiteUrl, repository, packages/remotes, icons, and version are accurate where available."""


class FixApiClient(Protocol):
    token: str
    base_url: str

    def current_user(self) -> dict[str, Any]: ...

    def list_submissions(self) -> list[dict[str, Any]]: ...

    def get_submission(self, submission_id: str) -> dict[str, Any]: ...


class Reviewer(Protocol):
    def review(self, prompt: str, *, environment: dict[str, str]) -> str: ...


class WardnHubFixApiClient(WardnHubApiClient):
    def update_submission(self, submission_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request(
            "PUT",
            f"/submissions/{urllib.parse.quote(submission_id, safe='')}",
            payload=payload,
        )

    def submit_submission(self, submission_id: str) -> dict[str, Any]:
        return self.request(
            "POST",
            "/submissions/submit",
            payload={"submissionId": submission_id},
        )


@dataclass
class FixStats:
    seen: int = 0
    candidate: int = 0
    fixed: int = 0
    skipped: int = 0
    failed: int = 0


REPAIRABLE_STATUSES = {"draft", "rejected"}


def submission_field(submission: dict[str, Any], snake_case: str, camel_case: str) -> Any:
    if camel_case in submission:
        return submission.get(camel_case)
    return submission.get(snake_case)


def current_user_id(user: dict[str, Any]) -> str:
    value = user.get("id")
    return str(value) if value else ""


def submission_owner_user_id(submission: dict[str, Any]) -> str:
    value = submission_field(submission, "owner_user_id", "ownerUserId")
    return str(value) if value else ""


def submission_owner_organization_id(submission: dict[str, Any]) -> str:
    value = submission_field(submission, "owner_organization_id", "ownerOrganizationId")
    return str(value) if value else ""


def ensure_active_user(client: FixApiClient) -> dict[str, Any]:
    user = client.current_user()
    if not bool_field(user, "is_active", "isActive"):
        raise UserFacingError("authenticated user is inactive")
    if not current_user_id(user):
        raise UserFacingError("authenticated user response did not include an id")
    return user


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


def can_fix_submission_for_user(submission: dict[str, Any], user_id: str) -> tuple[bool, str]:
    owner_organization_id = submission_owner_organization_id(submission)
    if owner_organization_id:
        return False, f"owned by organization {owner_organization_id}"
    owner_user_id = submission_owner_user_id(submission)
    if not owner_user_id:
        return False, "missing owner user"
    if owner_user_id != user_id:
        return False, f"owned by different user {owner_user_id}"
    return True, ""


def next_submission_to_fix(
    client: FixApiClient,
    *,
    user_id: str,
    skipped_ids: set[str],
    submission_id: str | None,
    stdout: TextIO,
) -> dict[str, Any] | None:
    if submission_id:
        if submission_id in skipped_ids:
            return None
        try:
            submission = client.get_submission(submission_id)
        except HubApiError as exc:
            if exc.status == 404:
                print(f"Submission {submission_id} was not found.", file=stdout)
                return None
            raise
        status = str(submission.get("status") or "")
        if status not in REPAIRABLE_STATUSES:
            print(
                f"Submission {submission_id} is not draft or rejected; skipping.",
                file=stdout,
            )
            skipped_ids.add(submission_id)
            return None
        can_fix, reason = can_fix_submission_for_user(submission, user_id)
        if not can_fix:
            print(f"Skipping {submission_id}: {reason}.", file=stdout)
            skipped_ids.add(submission_id)
            return None
        return submission

    for submission in repairable_submissions(client.list_submissions(), skipped_ids=skipped_ids):
        submission_id_value = str(submission.get("id") or "")
        can_fix, reason = can_fix_submission_for_user(submission, user_id)
        if can_fix:
            return submission
        skipped_ids.add(submission_id_value)
        print(f"Skipping {submission_label(submission)}: {reason}.", file=stdout)
    return None


def build_fix_context(
    client: FixApiClient,
    submission: dict[str, Any],
    *,
    user_id: str,
) -> dict[str, Any]:
    submission_id = str(submission["id"])
    fresh_submission = client.get_submission(submission_id)
    return {
        "apiBaseUrl": client.base_url,
        "submission": fresh_submission,
        "expectedOwnerUserId": user_id,
        "apiBaseUrlEnvironmentVariable": API_BASE_URL_ENV,
        "apiTokenEnvironmentVariable": TOKEN_ENV,
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
    expected_owner_user_id = str(context.get("expectedOwnerUserId") or "")

    return f"""Fix this Wardn Hub draft or rejected submission so it can be submitted for review.

Wardn Hub API base URL: {context.get("apiBaseUrl") or DEFAULT_API_BASE_URL}
Submission ID: {submission_id}
Server name: {server_name or "unknown"}
Version: {version or "unknown"}
Current status: {status}
Expected ownerUserId for this token: {expected_owner_user_id}
Current submit/review feedback: {rejection_message or "unknown"}

{API_ACCESS_INSTRUCTIONS}

Goal:
- Fetch the submission with GET /submissions/{submission_id}.
- Confirm the fetched submission has status "draft" or "rejected" and ownerUserId "{expected_owner_user_id}" before doing any source review or update work.
- If ownerUserId is absent, different, or organization-owned, stop immediately and report the mismatch. Do not fix it.
- Validate the submission against any submit/review feedback and Wardn Hub review requirements.
- Read the upstream source/docs needed to fix missing or incomplete metadata.
- Update the same submission with PUT /submissions/{submission_id}.
- Retry POST /submissions/submit with submissionId "{submission_id}".
- If submission still fails, repeat the fix/update/submit loop until it passes or the required information cannot be found.

Important:
- Do not create a new submission. Fix this existing draft or rejected submission only.
- Do not approve, reject, publish, withdraw, delete, or otherwise moderate this submission.
- Do not update submissions owned by any other user or organization.
- Do not guess source-review evidence. It must reflect URLs/files actually inspected.
- If the submission lacks enough source links to verify the server, stop and report the official repository or documentation URL needed from the user.
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

Return:
- final submission ID
- final status
- endpoints called
- source URLs/files read
- environment variables included
- command arguments included
- remaining validation warnings/errors, if any
- if you cannot fix it, the exact missing information needed from the user"""


def fix_loop(
    *,
    client: FixApiClient,
    reviewer: Reviewer,
    user: dict[str, Any],
    max_fixes: int | None,
    once: bool,
    dry_run: bool,
    stdout: TextIO,
    submission_id: str | None = None,
) -> int:
    user_id = current_user_id(user)
    skipped_ids: set[str] = set()
    stats = FixStats()

    while True:
        skipped_before = len(skipped_ids)
        submission = next_submission_to_fix(
            client,
            user_id=user_id,
            skipped_ids=skipped_ids,
            submission_id=submission_id,
            stdout=stdout,
        )
        stats.skipped += len(skipped_ids) - skipped_before
        if submission is None:
            if submission_id:
                print(
                    f"No eligible draft or rejected submission found for {submission_id}.",
                    file=stdout,
                )
            else:
                print("No eligible draft or rejected submissions remain for this user.", file=stdout)
            print_stats(stats, stdout)
            return 1 if stats.failed else 0

        stats.seen += 1
        current_submission_id = str(submission["id"])
        stats.candidate += 1
        print_heading(stdout, f"Fixing {submission_label(submission)}")

        if dry_run:
            context = build_fix_context(client, submission, user_id=user_id)
            prompt = build_fix_prompt(context)
            print(prompt, file=stdout)
            stats.skipped += 1
            skipped_ids.add(current_submission_id)
        else:
            context = build_fix_context(client, submission, user_id=user_id)
            fresh_submission = context["submission"]
            can_fix, reason = can_fix_submission_for_user(fresh_submission, user_id)
            fresh_status = str(fresh_submission.get("status") or "")
            if fresh_status not in REPAIRABLE_STATUSES or not can_fix:
                stats.skipped += 1
                skipped_ids.add(current_submission_id)
                suffix = reason or f"status is {fresh_status or '<unknown>'}"
                print(f"Skipping {current_submission_id}: {suffix}.", file=stdout)
            else:
                prompt = build_fix_prompt(context)
                environment = os.environ.copy()
                environment[TOKEN_ENV] = client.token
                environment[API_BASE_URL_ENV] = client.base_url
                environment["WARDN_HUB_FIX_SUBMISSION_ID"] = current_submission_id
                environment["WARDN_HUB_EXPECTED_OWNER_USER_ID"] = user_id

                try:
                    findings = reviewer.review(prompt, environment=environment)
                    print_heading(stdout, "LLM Fix Output")
                    print(findings, file=stdout)
                    final_submission = client.get_submission(current_submission_id)
                except UserFacingError as exc:
                    stats.failed += 1
                    skipped_ids.add(current_submission_id)
                    print(
                        f"Fix failed for {current_submission_id}; leaving submission unchanged: {exc}",
                        file=stdout,
                    )
                else:
                    final_status = str(final_submission.get("status") or "")
                    if final_status == "submitted":
                        stats.fixed += 1
                        print(f"Submitted {current_submission_id} for review.", file=stdout)
                    else:
                        stats.failed += 1
                        skipped_ids.add(current_submission_id)
                        print(
                            f"Fix did not submit {current_submission_id}; final status is {final_status or '<unknown>'}.",
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
            "Fix draft or rejected Wardn Hub MCP server submissions owned by the authenticated user, "
            "then resubmit them for review."
        )
    )
    parser.add_argument(
        "--url",
        "--api-base-url",
        dest="api_base_url",
        default=os.getenv(API_BASE_URL_ENV, DEFAULT_API_BASE_URL),
        help=(
            "Wardn Hub API base URL, for example https://hub.example.com/api/v1. "
            f"Defaults to ${API_BASE_URL_ENV} or {DEFAULT_API_BASE_URL}."
        ),
    )
    parser.add_argument(
        "--token",
        default=None,
        help=f"Wardn Hub API token. Defaults to ${TOKEN_ENV}.",
    )
    parser.add_argument(
        "--user-agent",
        default=os.getenv(USER_AGENT_ENV, DEFAULT_USER_AGENT),
        help=(
            "HTTP User-Agent sent to Wardn Hub. "
            f"Defaults to ${USER_AGENT_ENV} or {DEFAULT_USER_AGENT}."
        ),
    )
    parser.add_argument(
        "--review-command",
        default=os.getenv(REVIEW_COMMAND_ENV, DEFAULT_REVIEW_COMMAND),
        help=(
            "LLM fix command. The prompt is sent on stdin unless the command contains "
            "{prompt_file}. Defaults to Codex exec."
        ),
    )
    parser.add_argument(
        "--model",
        default=os.getenv(REVIEW_MODEL_ENV, ""),
        help=f"Model to pass to Codex exec. Defaults to ${REVIEW_MODEL_ENV}.",
    )
    parser.add_argument(
        "--thinking",
        "--reasoning-effort",
        dest="thinking",
        choices=THINKING_LEVELS,
        default=os.getenv(REVIEW_THINKING_ENV, ""),
        help=(
            "Thinking level to pass to Codex exec: low, medium, high, or xhigh. "
            f"Defaults to ${REVIEW_THINKING_ENV}."
        ),
    )
    parser.add_argument(
        "--review-timeout",
        type=int,
        default=900,
        help="Seconds to wait for each LLM fix command.",
    )
    parser.add_argument(
        "--review-progress-interval",
        type=int,
        default=int_from_env(REVIEW_PROGRESS_INTERVAL_ENV, 15),
        help=(
            "Seconds between progress messages while the review command is silent. "
            f"Set to 0 to disable. Defaults to ${REVIEW_PROGRESS_INTERVAL_ENV} or 15."
        ),
    )
    parser.add_argument(
        "--stream-review-output",
        action="store_true",
        help="Print reviewer stdout while it is produced. Implies --verbose.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show live review command logs, stderr, and progress status.",
    )
    parser.add_argument(
        "--http-timeout",
        type=int,
        default=30,
        help="Seconds to wait for Wardn Hub API requests.",
    )
    parser.add_argument(
        "--max-fixes",
        type=int,
        default=None,
        help="Maximum number of draft or rejected submissions to fix in this run.",
    )
    parser.add_argument(
        "--submission-id",
        default="",
        help="Fix exactly one draft or rejected submission ID.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Fix one draft or rejected submission and exit.",
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
        token = (args.token or os.getenv(TOKEN_ENV, "")).strip()
        if not token:
            print(
                f"Missing Wardn Hub API token. Pass --token or set {TOKEN_ENV}.",
                file=sys.stderr,
            )
            return 2

        client = WardnHubFixApiClient(
            base_url=args.api_base_url,
            token=token,
            user_agent=args.user_agent,
            timeout_seconds=args.http_timeout,
        )
        user = ensure_active_user(client)
        submission_id = args.submission_id.strip() or None
        if submission_id is None:
            client.list_submissions()

        if args.review_progress_interval < 0:
            raise UserFacingError("--review-progress-interval must be 0 or greater")
        verbose = bool(args.verbose or args.stream_review_output)
        review_command = parse_review_command(
            args.review_command,
            model=args.model,
            thinking=args.thinking,
        )
        if not args.dry_run:
            ensure_codex_login(review_command, environment=os.environ.copy(), stdout=sys.stdout)
        reviewer = SubprocessReviewer(
            command=review_command,
            timeout_seconds=args.review_timeout,
            cwd=Path.cwd(),
            progress_stream=sys.stdout if verbose else None,
            progress_interval_seconds=args.review_progress_interval,
            stream_stdout=args.stream_review_output,
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
            submission_id=submission_id,
        )
    except UserFacingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
