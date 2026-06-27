# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO

API_PREFIX = "/api/v1"
DEFAULT_API_BASE_URL = "http://localhost:8000/api/v1"
TOKEN_ENV = "WARDN_HUB_TOKEN"
API_BASE_URL_ENV = "WARDN_HUB_API_BASE_URL"
USER_AGENT_ENV = "WARDN_HUB_USER_AGENT"
REVIEW_COMMAND_ENV = "WARDN_HUB_REVIEW_COMMAND"
REVIEW_MODEL_ENV = "WARDN_HUB_REVIEW_MODEL"
REVIEW_THINKING_ENV = "WARDN_HUB_REVIEW_THINKING"
DEFAULT_USER_AGENT = "WardnHubReviewCLI/0.1"
DEFAULT_REVIEW_COMMAND = "codex --search exec --skip-git-repo-check -"
THINKING_LEVELS = ("low", "medium", "high", "xhigh")

API_ACCESS_INSTRUCTIONS = """Required API access:
- Use WARDN_HUB_TOKEN as the Wardn Hub bearer token.
- If WARDN_HUB_TOKEN is not available in the environment or context, stop and ask the user for a Wardn Hub API token.
- Do not call the Wardn Hub API until a token is available."""

REGISTRY_METADATA_SCOPE_RULE = (
    "Treat this as registry metadata review only. Do not install workspace MCP servers, "
    "invoke MCP tools, or manage runtime infrastructure."
)

VALIDATION_PACKAGE_ARGUMENT_CHECKS = """- packages[].transport.args contains only the concrete default launch arguments in runnable order, not every documented optional CLI flag.
- Optional CLI flags/configurable arguments are represented in packages[].packageArguments with includeInLaunch false.
- Flags that take user-supplied values are represented with packageArguments[].requiresValue true, not placeholder text in transport.args.
- packageArguments[].value does not contain placeholder examples such as "<host>", "[url]", "host", or "url"; requiresValue is the metadata for that.
- packageArguments[].flag does not contain placeholders. For docs that show "--host <host>", the correct shape is flag "--host" and requiresValue true.
- Package arguments that are part of the default launch command have includeInLaunch true."""

VALIDATION_REMOTE_QUERY_PARAMETER_CHECKS = """- Remote endpoint URLs do not include configurable query strings such as ?apiKey={apiKey}.
- Remote URL query parameters are represented in remotes[].queryParameters, not remotes[].authentication.queryParameters.
- If docs show a hosted URL with query authentication, the base endpoint is stored in remotes[].url and the query auth fields are stored in remotes[].queryParameters."""


class UserFacingError(Exception):
    """Error that should be shown without a traceback."""


@dataclass
class HubApiError(UserFacingError):
    status: int
    detail: str
    url: str

    def __str__(self) -> str:
        return f"{self.status} from {self.url}: {self.detail}"


class Reviewer(Protocol):
    def review(self, prompt: str, *, environment: dict[str, str]) -> str:
        """Return review findings for a prompt."""


@dataclass
class SubprocessReviewer:
    command: list[str]
    timeout_seconds: int
    cwd: Path | None = None

    def review(self, prompt: str, *, environment: dict[str, str]) -> str:
        command = self.command
        prompt_path: str | None = None
        input_text: str | None = prompt

        if any("{prompt_file}" in part for part in command):
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                prefix="wardn-review-",
                suffix=".md",
                delete=False,
            ) as prompt_file:
                prompt_file.write(prompt)
                prompt_path = prompt_file.name
            command = [part.format(prompt_file=prompt_path) for part in command]
            input_text = None

        try:
            completed = subprocess.run(
                command,
                input=input_text,
                text=True,
                capture_output=True,
                cwd=self.cwd,
                env=environment,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise UserFacingError(f"review command not found: {command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise UserFacingError(
                f"review command timed out after {self.timeout_seconds} seconds"
            ) from exc
        finally:
            if prompt_path is not None:
                try:
                    Path(prompt_path).unlink()
                except FileNotFoundError:
                    pass

        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            stdout = completed.stdout.strip()
            detail = stderr or stdout or f"exit code {completed.returncode}"
            raise UserFacingError(f"review command failed: {detail}")

        output = completed.stdout.strip()
        if not output:
            raise UserFacingError("review command completed without findings")
        return output


class WardnHubApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        user_agent: str,
        timeout_seconds: int,
    ) -> None:
        self.base_url = normalize_api_base_url(base_url)
        self.token = token
        self.user_agent = user_agent.strip() or DEFAULT_USER_AGENT
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        expected_statuses: Iterable[int] = (200,),
        allow_statuses: Iterable[int] = (),
    ) -> Any:
        expected = set(expected_statuses)
        allowed = set(allow_statuses)
        body = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": self.user_agent,
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")

        url = join_api_url(self.base_url, path)
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
                status = response.status
                content_type = response.headers.get("content-type", "")
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            if exc.code in allowed:
                return None
            raise HubApiError(exc.code, parse_error_detail(response_body), url) from exc
        except urllib.error.URLError as exc:
            message = f"could not connect to Wardn Hub API at {url}: {exc.reason}"
            raise UserFacingError(message) from exc

        if status in allowed:
            return None
        if status not in expected:
            raise HubApiError(status, f"unexpected status {status}", url)
        if status == 204 or not response_body:
            return None
        if "application/json" not in content_type:
            raise HubApiError(status, f"expected JSON response, received {content_type}", url)
        return json.loads(response_body)

    def current_user(self) -> dict[str, Any]:
        return self.request("GET", "/auth/me")

    def list_submissions(self) -> list[dict[str, Any]]:
        response = self.request("GET", "/submissions")
        submissions = response.get("submissions") if isinstance(response, dict) else []
        return submissions if isinstance(submissions, list) else []

    def get_submission(self, submission_id: str) -> dict[str, Any]:
        return self.request("GET", f"/submissions/{urllib.parse.quote(submission_id, safe='')}")

    def list_categories(self) -> dict[str, Any] | None:
        return self.request("GET", "/mcp/categories", allow_statuses=(403, 404))

    def get_server(self, server_name: str) -> dict[str, Any] | None:
        return self.request(
            "GET",
            f"/mcp/servers/{server_name_path(server_name)}",
            allow_statuses=(404,),
        )

    def list_versions(self, server_name: str) -> dict[str, Any] | None:
        return self.request(
            "GET",
            f"/mcp/servers/{server_name_path(server_name)}/versions",
            allow_statuses=(404,),
        )

    def approve_submission(self, submission_id: str) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/submissions/{urllib.parse.quote(submission_id, safe='')}/approve",
        )

    def publish_submission(self, submission_id: str) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/submissions/{urllib.parse.quote(submission_id, safe='')}/publish",
        )

    def reject_submission(self, submission_id: str, message: str) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/submissions/{urllib.parse.quote(submission_id, safe='')}/reject",
            payload={"message": message},
        )

    def probe_moderation_access(self) -> None:
        self.request(
            "POST",
            f"/submissions/{uuid.uuid4()}/approve",
            expected_statuses=(),
            allow_statuses=(404,),
        )

    def probe_publish_access(self) -> bool:
        try:
            self.request(
                "POST",
                f"/submissions/{uuid.uuid4()}/publish",
                expected_statuses=(),
                allow_statuses=(404,),
            )
        except HubApiError as exc:
            if exc.status == 403:
                return False
            raise
        return True


def normalize_api_base_url(value: str) -> str:
    raw_value = value.strip().rstrip("/")
    if not raw_value:
        raw_value = DEFAULT_API_BASE_URL

    parsed = urllib.parse.urlparse(raw_value)
    if not parsed.scheme or not parsed.netloc:
        raise UserFacingError(f"invalid API base URL: {value}")

    path = parsed.path.rstrip("/")
    if not path:
        path = API_PREFIX
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def join_api_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def server_name_path(value: str) -> str:
    return "/".join(urllib.parse.quote(part, safe="") for part in value.split("/"))


def parse_error_detail(body: str) -> str:
    if not body:
        return "empty error response"
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()
    detail = data.get("detail") if isinstance(data, dict) else None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        messages: list[str] = []
        for item in detail:
            if not isinstance(item, dict):
                continue
            location = item.get("loc")
            message = item.get("msg")
            location_text = (
                ".".join(str(part) for part in location)
                if isinstance(location, list)
                else ""
            )
            message_text = str(message) if message else ""
            messages.append(": ".join(part for part in (location_text, message_text) if part))
        return "; ".join(messages) if messages else json.dumps(detail)
    return json.dumps(data)


def bool_field(data: dict[str, Any], snake_case: str, camel_case: str) -> bool:
    return bool(data.get(snake_case) or data.get(camel_case))


def validate_token(client: WardnHubApiClient) -> dict[str, Any]:
    user = client.current_user()
    if not bool_field(user, "is_active", "isActive"):
        raise UserFacingError("authenticated user is inactive")
    if not (
        bool_field(user, "is_superuser", "isSuperuser")
        or bool_field(user, "is_global_moderator", "isGlobalModerator")
    ):
        raise UserFacingError("authenticated user must be a superuser or global moderator")
    client.list_submissions()
    try:
        client.probe_moderation_access()
    except HubApiError as exc:
        if exc.status == 403:
            raise UserFacingError(
                "API token must include submissions:moderate for review decisions"
            ) from exc
        raise
    user["_wardnHubCanPublish"] = (
        bool_field(user, "is_superuser", "isSuperuser") and client.probe_publish_access()
    )
    return user


def pending_submissions(
    submissions: Iterable[dict[str, Any]],
    *,
    skipped_ids: set[str],
) -> list[dict[str, Any]]:
    return [
        submission
        for submission in submissions
        if submission.get("status") == "submitted"
        and str(submission.get("id") or "") not in skipped_ids
    ]


def build_review_context(client: WardnHubApiClient, submission: dict[str, Any]) -> dict[str, Any]:
    submission_id = str(submission["id"])
    fresh_submission = client.get_submission(submission_id)
    return {
        "apiBaseUrl": client.base_url,
        "submission": fresh_submission,
        "apiBaseUrlEnvironmentVariable": API_BASE_URL_ENV,
        "apiTokenEnvironmentVariable": TOKEN_ENV,
    }


def build_review_prompt(context: dict[str, Any]) -> str:
    submission = context.get("submission") if isinstance(context.get("submission"), dict) else {}
    submission_id = str(submission.get("id") or "")
    server_name = str(submission.get("name") or "")
    version = str(submission.get("version") or "")
    id_list = f"- {submission_id}" if submission_id else "- none"
    expected_version = version or "the listed version"

    return f"""Validate one Wardn Hub MCP server version that is currently in review.

Wardn Hub API base URL: {context.get("apiBaseUrl") or DEFAULT_API_BASE_URL}
Server: {server_name}
Version: {version or "unknown"}
In-review submission ID shown in UI:
{id_list}

{API_ACCESS_INSTRUCTIONS}
- The token must belong to an admin or moderator account with review-system access and must be able to read the submitted queue.
- The token must include submissions:read to inspect submissions and submissions:moderate to approve or reject submissions.
- To publish, the token must belong to a superuser and include submissions:publish.
- Moderator tokens may approve or reject submitted versions. Publishing and archiving require a superuser token.
- If GET /submissions does not expose submitted records for review, stop and report that the token does not have review access.
- Do not approve, reject, publish, update, or delete anything before presenting your validation report and receiving explicit user approval for the exact action.

Scope:
1. Validate only the in-review submission ID listed above.
2. Call GET /submissions/{{id}} before reviewing details.
3. Confirm the fetched submission has status "submitted", name "{server_name}", and version "{expected_version}". In the Wardn Hub UI, this status is shown as "In review".
4. Ignore any other submissions returned by the API, including drafts, approved submissions, rejected submissions, withdrawn submissions, published submissions, other versions, and submissions for other servers.
5. If the listed ID cannot be fetched as an in-review submission for this version, report that clearly and stop.

Validation workflow for each submission:
1. Read submission.serverJson, submission.validationResult, and submission.serverJson._meta.sourceReview.
2. Identify the source repository from serverJson.repository.url and any source links in documentation/package metadata.
3. Read the upstream README and relevant docs/files needed to verify installation, package transport, environment variables, CLI arguments, prerequisites, capabilities, limitations, and version/package metadata.
4. Compare the source review evidence against the upstream source. Do not assume importer output is complete.
5. {REGISTRY_METADATA_SCOPE_RULE}

Required checks:
- Registry name, title, description, website, repository, version, icons, packages, remotes, and documentation are present and accurate where applicable.
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
- validationResult has no failing checks that remain unresolved.

Report format:
- Submission ID
- Server name and version
- Repository/source files reviewed
- Decision: pass, needs fixes, or cannot validate
- Findings grouped by severity
- Missing or incorrect environment variables
- Missing or incorrect command arguments
- Suggested rejection message if the submission should be rejected
- Suggested approval note if the submission passes

After the report:
- Ask the user exactly what action to take using lettered options so they can reply with a single letter. If the token has moderator-only access, display:
  A. Approve
  B. Reject with the suggested message
  C. Leave unchanged
- If the token has superuser publishing access, display:
  A. Approve
  B. Approve and publish
  C. Reject with the suggested message
  D. Leave unchanged
- Do not take action from your own recommendation alone.
- Only after the user explicitly chooses one lettered option or the exact action text, call the corresponding Wardn Hub API endpoint.
- If the user chooses approve, call POST /submissions/{{id}}/approve.
- If the user chooses approve and publish, first call POST /submissions/{{id}}/approve, then call POST /submissions/{{id}}/publish on the approved submission. Only offer and perform this when the token has superuser publishing access.
- If the user chooses reject, call POST /submissions/{{id}}/reject with a clear message.
- Do not publish unless the user explicitly chose approve and publish.
- After performing an approved action, return the endpoints called, final submission status, and any API error.

Do not mark a submission as passing if source review evidence is incomplete, upstream docs mention an env var/argument/prerequisite that is missing, or package transport details cannot be verified."""


def codex_exec_index(command: list[str]) -> int | None:
    if not command or Path(command[0]).name != "codex":
        return None
    try:
        return command.index("exec", 1)
    except ValueError:
        return None


def parse_review_command(value: str, *, model: str = "", thinking: str = "") -> list[str]:
    try:
        command = shlex.split(value)
    except ValueError as exc:
        raise UserFacingError(f"invalid review command: {exc}") from exc
    if not command:
        raise UserFacingError("review command cannot be empty")
    model = model.strip()
    thinking = thinking.strip()
    if not model and not thinking:
        return command
    exec_index = codex_exec_index(command)
    if exec_index is None:
        raise UserFacingError(
            "--model and --thinking are only applied automatically to `codex exec`; include "
            "equivalent flags inside --review-command for other LLM CLIs"
        )
    codex_options: list[str] = []
    if model:
        codex_options.extend(["--model", model])
    if thinking:
        codex_options.extend(["-c", f'model_reasoning_effort="{thinking}"'])
    insert_at = exec_index + 1
    return [*command[:insert_at], *codex_options, *command[insert_at:]]


def submission_label(submission: dict[str, Any]) -> str:
    name = submission.get("name") or "<unknown>"
    version = submission.get("version") or "<unknown>"
    submission_id = submission.get("id") or "<unknown>"
    return f"{name}@{version} ({submission_id})"


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


def apply_decision(
    client: WardnHubApiClient,
    submission_id: str,
    decision: str,
    *,
    dry_run: bool,
    stdin: TextIO,
    stdout: TextIO,
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
    client: WardnHubApiClient,
    reviewer: Reviewer,
    user: dict[str, Any],
    max_reviews: int | None,
    once: bool,
    dry_run: bool,
    stdin: TextIO,
    stdout: TextIO,
) -> int:
    skipped_ids: set[str] = set()
    completed_reviews = 0
    can_publish = bool(user.get("_wardnHubCanPublish"))

    while True:
        submissions = client.list_submissions()
        pending = pending_submissions(submissions, skipped_ids=skipped_ids)
        if not pending:
            print("No submitted MCP server submissions remain for this run.", file=stdout)
            return 0

        submission = pending[0]
        submission_id = str(submission["id"])
        print_heading(stdout, f"Reviewing {submission_label(submission)}")
        context = build_review_context(client, submission)
        prompt = build_review_prompt(context)
        environment = os.environ.copy()
        environment[TOKEN_ENV] = client.token
        environment[API_BASE_URL_ENV] = client.base_url
        environment["WARDN_HUB_REVIEW_SUBMISSION_ID"] = submission_id

        findings = reviewer.review(prompt, environment=environment)
        print_heading(stdout, "LLM Findings")
        print(findings, file=stdout)

        decision = read_decision(stdin, stdout, can_publish=can_publish)
        if decision == "quit":
            print("Stopping review loop.", file=stdout)
            return 0
        if decision == "skip":
            skipped_ids.add(submission_id)
            print(f"Skipped {submission_id} for this run.", file=stdout)
        else:
            apply_decision(
                client,
                submission_id,
                decision,
                dry_run=dry_run,
                stdin=stdin,
                stdout=stdout,
            )

        completed_reviews += 1
        if once or (max_reviews is not None and completed_reviews >= max_reviews):
            print("Review limit reached.", file=stdout)
            return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Review submitted Wardn Hub MCP server submissions with an LLM, then apply "
            "human-selected moderation actions."
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
            "LLM review command. The prompt is sent on stdin unless the command contains "
            "{prompt_file}. Defaults to Codex exec."
        ),
    )
    parser.add_argument(
        "--model",
        default=os.getenv(REVIEW_MODEL_ENV, ""),
        help=(
            f"Model to pass to Codex exec. Defaults to ${REVIEW_MODEL_ENV}."
        ),
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
        help="Seconds to wait for each LLM review command.",
    )
    parser.add_argument(
        "--http-timeout",
        type=int,
        default=30,
        help="Seconds to wait for Wardn Hub API requests.",
    )
    parser.add_argument(
        "--max-reviews",
        type=int,
        default=None,
        help="Maximum number of submissions to review in this run.",
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    token = (args.token or os.getenv(TOKEN_ENV, "")).strip()
    if not token:
        print(
            f"Missing Wardn Hub API token. Pass --token or set {TOKEN_ENV}.",
            file=sys.stderr,
        )
        return 2

    try:
        client = WardnHubApiClient(
            base_url=args.api_base_url,
            token=token,
            user_agent=args.user_agent,
            timeout_seconds=args.http_timeout,
        )
        user = validate_token(client)
        reviewer = SubprocessReviewer(
            command=parse_review_command(
                args.review_command,
                model=args.model,
                thinking=args.thinking,
            ),
            timeout_seconds=args.review_timeout,
            cwd=Path.cwd(),
        )
        print(f"Authenticated as {display_user(user)}.", file=sys.stdout)
        return review_loop(
            client=client,
            reviewer=reviewer,
            user=user,
            max_reviews=args.max_reviews,
            once=args.once,
            dry_run=args.dry_run,
            stdin=sys.stdin,
            stdout=sys.stdout,
        )
    except UserFacingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
