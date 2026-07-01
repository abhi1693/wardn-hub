# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
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
REVIEW_PROGRESS_INTERVAL_ENV = "WARDN_HUB_REVIEW_PROGRESS_INTERVAL"
DEFAULT_USER_AGENT = "WardnHubReviewCLI/0.1"
DEFAULT_REVIEW_COMMAND = (
    "codex --search exec --ephemeral --sandbox danger-full-access --ignore-user-config "
    "--skip-git-repo-check -"
)
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
- Package arguments that are part of the default launch command have includeInLaunch true.
- packageArguments contain only server process args after the package/image, not package-manager wrapper args such as npx/npm/uvx/pipx/docker, install/run flags, or the package/image identifier."""

VALIDATION_REMOTE_QUERY_PARAMETER_CHECKS = """- Remote endpoint URLs do not include configurable query strings such as ?apiKey={apiKey}.
- Remote URL query parameters are represented in remotes[].queryParameters, not remotes[].authentication.queryParameters.
- If docs show a hosted URL with query authentication, the base endpoint is stored in remotes[].url and the query auth fields are stored in remotes[].queryParameters."""


class UserFacingError(Exception):
    """Error that should be shown without a traceback."""


def int_from_env(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise UserFacingError(f"${name} must be an integer") from exc


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
    progress_stream: TextIO | None = None
    progress_interval_seconds: int = 15
    stream_stdout: bool = False

    def _progress_stream_is_tty(self) -> bool:
        isatty = getattr(self.progress_stream, "isatty", None)
        return bool(isatty and isatty())

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
            return self._run_review_command(
                command,
                input_text=input_text,
                environment=environment,
            )
        except FileNotFoundError as exc:
            raise UserFacingError(f"review command not found: {command[0]}") from exc
        finally:
            if prompt_path is not None:
                try:
                    Path(prompt_path).unlink()
                except FileNotFoundError:
                    pass

    def _run_review_command(
        self,
        command: list[str],
        *,
        input_text: str | None,
        environment: dict[str, str],
    ) -> str:
        progress_stream = self.progress_stream
        if progress_stream is not None:
            print(
                "Review command started. Waiting for reviewer output; long source checks can take several minutes.",
                file=progress_stream,
                flush=True,
            )

        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE if input_text is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.cwd,
            env=environment,
            bufsize=1,
        )
        output_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        def enqueue_output(name: str, stream: TextIO | None) -> None:
            if stream is None:
                return
            try:
                for line in iter(stream.readline, ""):
                    output_queue.put((name, line))
            finally:
                stream.close()

        stdout_thread = threading.Thread(
            target=enqueue_output,
            args=("stdout", process.stdout),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=enqueue_output,
            args=("stderr", process.stderr),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        if input_text is not None and process.stdin is not None:
            try:
                process.stdin.write(input_text)
                process.stdin.close()
            except BrokenPipeError:
                pass

        deadline = time.monotonic() + self.timeout_seconds
        last_progress = time.monotonic()
        status_line_open = False

        def clear_status_line() -> None:
            nonlocal status_line_open
            if progress_stream is not None and status_line_open and self._progress_stream_is_tty():
                print("\r\033[K", end="", file=progress_stream, flush=True)
                status_line_open = False

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                clear_status_line()
                process.kill()
                process.wait()
                raise UserFacingError(
                    f"review command timed out after {self.timeout_seconds} seconds"
                )

            try:
                name, chunk = output_queue.get(timeout=min(0.5, remaining))
            except queue.Empty:
                if (
                    progress_stream is not None
                    and self.progress_interval_seconds > 0
                    and time.monotonic() - last_progress >= self.progress_interval_seconds
                    and process.poll() is None
                ):
                    elapsed = int(time.monotonic() - (deadline - self.timeout_seconds))
                    message = f"Review command still running after {elapsed}s..."
                    if self._progress_stream_is_tty():
                        print(f"\r\033[K{message}", end="", file=progress_stream, flush=True)
                        status_line_open = True
                    elif not status_line_open:
                        print(message, file=progress_stream, flush=True)
                        status_line_open = True
                    last_progress = time.monotonic()

                if (
                    process.poll() is not None
                    and output_queue.empty()
                    and not stdout_thread.is_alive()
                    and not stderr_thread.is_alive()
                ):
                    break
                continue

            if name == "stdout":
                stdout_chunks.append(chunk)
                if self.stream_stdout and progress_stream is not None:
                    clear_status_line()
                    print(chunk, end="", file=progress_stream, flush=True)
            else:
                stderr_chunks.append(chunk)
                if progress_stream is not None:
                    clear_status_line()
                    print(chunk, end="", file=progress_stream, flush=True)

        clear_status_line()
        return_code = process.wait()
        output = "".join(stdout_chunks).strip()
        stderr = "".join(stderr_chunks).strip()
        if return_code != 0:
            detail = stderr or output or f"exit code {return_code}"
            raise UserFacingError(f"review command failed: {detail}")
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
        except TimeoutError as exc:
            message = f"timed out after {self.timeout_seconds} seconds reading Wardn Hub API response from {url}"
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

Decision rules:
- Use "pass" only when the submitted metadata can be verified against source evidence.
- Use "needs fixes" or "reject" only when the submitted metadata is clearly wrong or incomplete.
- Use "cannot validate" when source evidence is unavailable, ambiguous, or insufficient to make a safe approval/rejection decision. This leaves the submission unchanged so it can be retried or reviewed manually later.

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


def command_uses_codex(command: list[str]) -> bool:
    return bool(command and Path(command[0]).name == "codex")


def ensure_codex_login(command: list[str], *, environment: dict[str, str], stdout: TextIO) -> None:
    if not command_uses_codex(command):
        return

    try:
        status = subprocess.run(
            ["codex", "login", "status"],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError as exc:
        raise UserFacingError("codex command not found; install @openai/codex") from exc
    if status.returncode == 0:
        return

    print(
        "Codex is not logged in. Starting `codex login --device-auth`; "
        "complete the device login shown below to continue.",
        file=stdout,
        flush=True,
    )
    try:
        login = subprocess.run(
            ["codex", "login", "--device-auth"],
            env=environment,
            check=False,
        )
    except FileNotFoundError as exc:
        raise UserFacingError("codex command not found; install @openai/codex") from exc
    if login.returncode != 0:
        raise UserFacingError(f"codex login failed with exit code {login.returncode}")


def submission_label(submission: dict[str, Any]) -> str:
    name = submission.get("name") or "<unknown>"
    version = submission.get("version") or "<unknown>"
    submission_id = submission.get("id") or "<unknown>"
    return f"{name}@{version} ({submission_id})"


def next_submission_for_review(
    client: WardnHubApiClient,
    *,
    skipped_ids: set[str],
    submission_id: str | None,
) -> dict[str, Any] | None:
    if submission_id:
        if submission_id in skipped_ids:
            return None
        try:
            submission = client.get_submission(submission_id)
        except HubApiError as exc:
            if exc.status == 404:
                return None
            raise
        if submission.get("status") != "submitted":
            return None
        return submission

    submissions = client.list_submissions()
    pending = pending_submissions(submissions, skipped_ids=skipped_ids)
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


def extract_review_decision(findings: str) -> str | None:
    match = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:#+\s*)?Decision\s*:\s*(.+?)\s*$", findings)
    if match is None:
        return None

    decision = re.sub(r"[`*_]", "", match.group(1)).strip().lower()
    decision = re.sub(r"\s+", " ", decision)
    if decision.startswith("pass"):
        return "pass"
    if decision.startswith("needs fixes") or decision.startswith("needs fix"):
        return "needs_fixes"
    if (
        decision.startswith("cannot validate")
        or decision.startswith("cannot determine")
        or decision.startswith("uncertain")
        or decision.startswith("unsure")
    ):
        return "cannot_validate"
    if decision.startswith("skip") or decision.startswith("leave unchanged"):
        return "skip"
    if decision.startswith("reject") or decision.startswith("rejected"):
        return "reject"
    return None


def should_auto_reject(findings: str) -> bool:
    return extract_review_decision(findings) in {"needs_fixes", "reject"}


def should_auto_skip(findings: str) -> bool:
    return extract_review_decision(findings) in {"cannot_validate", "skip"}


def should_auto_approve(findings: str) -> bool:
    return extract_review_decision(findings) == "pass"


def extract_suggested_rejection_message(findings: str) -> str | None:
    match = re.search(
        r"(?im)^\s*(?:[-*]\s*)?(?:#+\s*)?Suggested rejection message\s*:?\s*$",
        findings,
    )
    if match is None:
        return None

    remaining = findings[match.end() :].lstrip()
    fenced = re.match(r"```[^\n]*\n(?P<message>.*?)\n```", remaining, flags=re.DOTALL)
    if fenced is not None:
        return normalize_suggested_rejection_message(fenced.group("message"))

    next_section = re.search(
        r"(?im)^\s*(?:[-*]\s*)?(?:#+\s*)?"
        r"(?:Suggested approval note|Available actions|Decision|After the report|Submission ID|"
        r"Server name and version|Repository/source files reviewed|Findings grouped by severity|"
        r"Missing or incorrect environment variables|Missing or incorrect command arguments)\s*:?\s*$",
        remaining,
    )
    message = remaining[: next_section.start()] if next_section is not None else remaining
    return normalize_suggested_rejection_message(message)


def apply_decision(
    client: WardnHubApiClient,
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
    client: WardnHubApiClient,
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
        environment = os.environ.copy()
        environment[TOKEN_ENV] = client.token
        environment[API_BASE_URL_ENV] = client.base_url
        environment["WARDN_HUB_REVIEW_SUBMISSION_ID"] = current_submission_id

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

        suggested_rejection_message = extract_suggested_rejection_message(findings)
        if should_auto_skip(findings):
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

        if auto_reject and should_auto_reject(findings):
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

        if auto_publish and should_auto_approve(findings):
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

        if auto_approve and not auto_publish and should_auto_approve(findings):
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
        help=(
            "Print reviewer stdout while it is produced. Implies --verbose. Findings are "
            "still captured and shown again before the moderation prompt."
        ),
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
        "--max-reviews",
        type=int,
        default=None,
        help="Maximum number of submissions to review in this run.",
    )
    parser.add_argument(
        "--submission-id",
        default="",
        help=(
            "Review exactly one submitted submission ID. Useful for webhook-driven review jobs."
        ),
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
            "Automatically approve and publish reviews whose LLM decision is pass. Requires "
            "a superuser token with submissions:publish access."
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
        token = (args.token or os.getenv(TOKEN_ENV, "")).strip()
        if not token:
            print(
                f"Missing Wardn Hub API token. Pass --token or set {TOKEN_ENV}.",
                file=sys.stderr,
            )
            return 2

        client = WardnHubApiClient(
            base_url=args.api_base_url,
            token=token,
            user_agent=args.user_agent,
            timeout_seconds=args.http_timeout,
        )
        user = validate_token(client)
        if args.review_progress_interval < 0:
            raise UserFacingError("--review-progress-interval must be 0 or greater")
        verbose = bool(args.verbose or args.stream_review_output)
        review_command = parse_review_command(
            args.review_command,
            model=args.model,
            thinking=args.thinking,
        )
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
