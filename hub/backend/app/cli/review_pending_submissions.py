from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
import textwrap
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
DEFAULT_REVIEW_COMMAND = "codex exec --sandbox read-only --skip-git-repo-check -"
THINKING_LEVELS = ("low", "medium", "high", "xhigh")


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


def compact_context_for_prompt(context: dict[str, Any]) -> str:
    return json.dumps(context, indent=2, sort_keys=True, ensure_ascii=False)


def build_review_context(client: WardnHubApiClient, submission: dict[str, Any]) -> dict[str, Any]:
    submission_id = str(submission["id"])
    fresh_submission = client.get_submission(submission_id)
    name = str(fresh_submission.get("name") or "")
    context: dict[str, Any] = {
        "submission": fresh_submission,
        "availableReadApis": [
            {"method": "GET", "path": "/auth/me"},
            {"method": "GET", "path": "/submissions"},
            {"method": "GET", "path": f"/submissions/{submission_id}"},
            {"method": "GET", "path": "/mcp/categories"},
            {"method": "GET", "path": f"/mcp/servers/{name}"},
            {"method": "GET", "path": f"/mcp/servers/{name}/versions"},
        ],
        "apiBaseUrlEnvironmentVariable": API_BASE_URL_ENV,
        "apiTokenEnvironmentVariable": TOKEN_ENV,
    }

    categories = client.list_categories()
    if categories is not None:
        context["categories"] = categories

    if name:
        existing_server = client.get_server(name)
        existing_versions = client.list_versions(name)
        if existing_server is not None:
            context["existingPublishedServer"] = existing_server
        if existing_versions is not None:
            context["existingPublishedVersions"] = existing_versions

    return context


def build_review_prompt(context: dict[str, Any]) -> str:
    return textwrap.dedent(
        f"""
        You are reviewing a Wardn Hub MCP server submission for registry moderation.

        Wardn Hub is a registry and submission product for MCP server definitions. It is
        not a runtime product. Do not recommend adding workspace MCP installs, MCP tool
        invocation routes, Kubernetes runtime management, or a gateway execution plane.

        Use the supplied JSON context first. If you need to verify something else, you may
        make read-only GET requests to the Wardn Hub API using `{API_BASE_URL_ENV}` and
        `{TOKEN_ENV}` from the environment. Do not call POST, PUT, PATCH, or DELETE. The
        CLI will apply moderator decisions after a human chooses an action.

        Review the submission for:
        - Accurate name, version, submission type, owner, and category metadata.
        - Complete source-review evidence: files read, install commands, command args,
          environment variables, prerequisites, capabilities, limitations, and unknowns.
        - Package and remote target correctness, including no version embedded in package
          identifiers and no secret/plaintext placeholder values.
        - Documentation quality for setup, configuration, authentication, capabilities,
          limitations, and support.
        - Consistency with validationResult and any existing published server context.
        - Publication risk that should lead to rejection or a specific rejection message.

        Return concise Markdown with these sections:

        ## Summary
        ## Findings
        ## Recommended decision
        Use exactly one of: approve, approve_and_publish, reject, skip.
        ## Rejection message
        Include a ready-to-send message only if rejection is recommended.

        Context JSON:

        ```json
        {compact_context_for_prompt(context)}
        ```
        """
    ).strip()


def is_codex_exec_command(command: list[str]) -> bool:
    return len(command) >= 2 and Path(command[0]).name == "codex" and command[1] == "exec"


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
    if not is_codex_exec_command(command):
        raise UserFacingError(
            "--model and --thinking are only applied automatically to `codex exec`; include "
            "equivalent flags inside --review-command for other LLM CLIs"
        )
    codex_options: list[str] = []
    if model:
        codex_options.extend(["--model", model])
    if thinking:
        codex_options.extend(["-c", f'model_reasoning_effort="{thinking}"'])
    return [*command[:2], *codex_options, *command[2:]]


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
