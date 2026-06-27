from __future__ import annotations

import sys
from io import StringIO
from typing import Any
from unittest.mock import patch

import pytest

from app.cli import review_pending_submissions as cli


class TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class FakeClient:
    def __init__(self, submissions: list[dict[str, Any]] | None = None) -> None:
        self.token = "wardn_hub_test_token"
        self.base_url = "http://localhost:8000/api/v1"
        self.user_agent = cli.DEFAULT_USER_AGENT
        self.submissions = submissions or []
        self.actions: list[tuple[str, str, str | None]] = []

    def current_user(self) -> dict[str, Any]:
        return {
            "id": "user-1",
            "email": "reviewer@example.com",
            "display_name": "Reviewer",
            "is_active": True,
            "is_superuser": True,
            "is_global_moderator": True,
        }

    def list_submissions(self) -> list[dict[str, Any]]:
        return self.submissions

    def get_submission(self, submission_id: str) -> dict[str, Any]:
        for submission in self.submissions:
            if submission["id"] == submission_id:
                return submission
        raise AssertionError(f"unknown submission {submission_id}")

    def list_categories(self) -> dict[str, Any]:
        return {"categories": [{"slug": "developer-tools", "name": "Developer Tools"}]}

    def get_server(self, server_name: str) -> dict[str, Any] | None:
        return None

    def list_versions(self, server_name: str) -> dict[str, Any] | None:
        return None

    def approve_submission(self, submission_id: str) -> dict[str, Any]:
        self.actions.append(("approve", submission_id, None))
        return {"id": submission_id, "status": "approved"}

    def publish_submission(self, submission_id: str) -> dict[str, Any]:
        self.actions.append(("publish", submission_id, None))
        return {"id": submission_id, "status": "published"}

    def reject_submission(self, submission_id: str, message: str) -> dict[str, Any]:
        self.actions.append(("reject", submission_id, message))
        return {"id": submission_id, "status": "rejected"}

    def probe_moderation_access(self) -> None:
        return None

    def probe_publish_access(self) -> bool:
        return True


class FakeReviewer:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def review(self, prompt: str, *, environment: dict[str, str]) -> str:
        self.prompts.append(prompt)
        assert environment[cli.TOKEN_ENV] == "wardn_hub_test_token"
        assert environment[cli.API_BASE_URL_ENV] == "http://localhost:8000/api/v1"
        return "## Summary\nLooks structurally valid.\n\n## Recommended decision\napprove"


def submitted_submission() -> dict[str, Any]:
    return {
        "id": "sub-1",
        "name": "io.github.example/weather",
        "version": "1.0.0",
        "status": "submitted",
        "submissionType": "new_server",
        "serverJson": {
            "name": "io.github.example/weather",
            "version": "1.0.0",
            "description": "Weather tools.",
            "packages": [{"registryType": "npm", "identifier": "@example/weather"}],
            "_meta": {"categories": ["developer-tools"]},
        },
        "validationResult": {"status": "passed", "checks": []},
    }


def submitted_submission_with_id(submission_id: str) -> dict[str, Any]:
    submission = submitted_submission()
    submission["id"] = submission_id
    return submission


def test_normalize_api_base_url_adds_default_api_prefix() -> None:
    assert cli.normalize_api_base_url("http://localhost:8000") == "http://localhost:8000/api/v1"
    assert cli.normalize_api_base_url("http://localhost:8000/api/v1/") == (
        "http://localhost:8000/api/v1"
    )


def test_url_alias_sets_api_base_url() -> None:
    args = cli.build_parser().parse_args(["--url", "https://hub.example.com/api/v1"])

    assert args.api_base_url == "https://hub.example.com/api/v1"


def test_user_agent_argument_overrides_default() -> None:
    args = cli.build_parser().parse_args(["--user-agent", "WardnHubReviewCLI/edge-test"])

    assert args.user_agent == "WardnHubReviewCLI/edge-test"


def test_default_review_command_uses_portable_codex_exec_flags() -> None:
    args = cli.build_parser().parse_args([])

    assert args.review_command == (
        "codex --search exec --sandbox danger-full-access --ignore-user-config "
        "--skip-git-repo-check -"
    )
    assert "--ask-for-approval" not in args.review_command
    assert "--ignore-user-config" in args.review_command


def test_model_argument_is_inserted_into_codex_exec_command() -> None:
    command = cli.parse_review_command(
        "codex exec --sandbox read-only --skip-git-repo-check -",
        model="gpt-5",
    )

    assert command == [
        "codex",
        "exec",
        "--model",
        "gpt-5",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "-",
    ]


def test_model_argument_is_inserted_after_codex_exec_with_top_level_flags() -> None:
    command = cli.parse_review_command(
        "codex --search exec --sandbox read-only --skip-git-repo-check -",
        model="gpt-5",
    )

    assert command == [
        "codex",
        "--search",
        "exec",
        "--model",
        "gpt-5",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "-",
    ]


def test_thinking_argument_is_inserted_into_codex_exec_command() -> None:
    command = cli.parse_review_command(
        "codex exec --sandbox read-only --skip-git-repo-check -",
        thinking="xhigh",
    )

    assert command == [
        "codex",
        "exec",
        "-c",
        'model_reasoning_effort="xhigh"',
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "-",
    ]


def test_model_and_thinking_arguments_are_inserted_before_codex_prompt() -> None:
    command = cli.parse_review_command(
        "codex exec --sandbox read-only --skip-git-repo-check -",
        model="gpt-5",
        thinking="high",
    )

    assert command == [
        "codex",
        "exec",
        "--model",
        "gpt-5",
        "-c",
        'model_reasoning_effort="high"',
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "-",
    ]


def test_model_argument_requires_codex_exec_command() -> None:
    with pytest.raises(cli.UserFacingError, match="codex exec"):
        cli.parse_review_command("custom-llm --review -", model="gpt-5")


def test_thinking_argument_requires_codex_exec_command() -> None:
    with pytest.raises(cli.UserFacingError, match="codex exec"):
        cli.parse_review_command("custom-llm --review -", thinking="high")


def test_thinking_argument_accepts_expected_levels() -> None:
    for level in ("low", "medium", "high", "xhigh"):
        args = cli.build_parser().parse_args(["--thinking", level])
        assert args.thinking == level


def test_review_progress_arguments() -> None:
    default_args = cli.build_parser().parse_args([])
    args = cli.build_parser().parse_args(
        ["--review-progress-interval", "30", "--stream-review-output", "--verbose"]
    )

    assert default_args.review_progress_interval == 15
    assert default_args.verbose is False
    assert default_args.stream_review_output is False
    assert args.review_progress_interval == 30
    assert args.stream_review_output is True
    assert args.verbose is True


def test_review_progress_interval_env_requires_integer(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(cli.REVIEW_PROGRESS_INTERVAL_ENV, "soon")

    assert cli.main(["--token", "wardn_hub_test_token"]) == 1
    assert "$WARDN_HUB_REVIEW_PROGRESS_INTERVAL must be an integer" in capsys.readouterr().err


def test_subprocess_reviewer_streams_stderr_and_captures_stdout() -> None:
    progress = StringIO()
    reviewer = cli.SubprocessReviewer(
        command=[
            sys.executable,
            "-c",
            "import sys; print('review progress', file=sys.stderr); print('final findings')",
        ],
        timeout_seconds=5,
        progress_stream=progress,
        progress_interval_seconds=0,
    )

    findings = reviewer.review("prompt", environment={})

    assert findings == "final findings"
    assert "Review command started" in progress.getvalue()
    assert "review progress" in progress.getvalue()
    assert "final findings" not in progress.getvalue()


def test_subprocess_reviewer_can_stream_stdout_while_capturing_findings() -> None:
    progress = StringIO()
    reviewer = cli.SubprocessReviewer(
        command=[sys.executable, "-c", "print('final findings')"],
        timeout_seconds=5,
        progress_stream=progress,
        progress_interval_seconds=0,
        stream_stdout=True,
    )

    findings = reviewer.review("prompt", environment={})

    assert findings == "final findings"
    assert "final findings" in progress.getvalue()


def test_subprocess_reviewer_refreshes_tty_heartbeat_status_line() -> None:
    progress = TtyStringIO()
    reviewer = cli.SubprocessReviewer(
        command=[
            sys.executable,
            "-c",
            "import time; time.sleep(1.1); print('final findings')",
        ],
        timeout_seconds=5,
        progress_stream=progress,
        progress_interval_seconds=1,
    )

    findings = reviewer.review("prompt", environment={})
    progress_output = progress.getvalue()

    assert findings == "final findings"
    assert "Review command still running after" in progress_output
    assert "\r\033[KReview command still running after" in progress_output
    assert "\nReview command still running after" not in progress_output


def test_main_keeps_review_command_logs_quiet_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_reviewers: list[dict[str, Any]] = []

    class FakeApiClient(FakeClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__([])

    class CapturingSubprocessReviewer:
        def __init__(self, **kwargs: Any) -> None:
            captured_reviewers.append(kwargs)

    monkeypatch.setattr(cli, "WardnHubApiClient", FakeApiClient)
    monkeypatch.setattr(cli, "SubprocessReviewer", CapturingSubprocessReviewer)

    result = cli.main(["--token", "wardn_hub_test_token", "--once"])

    assert result == 0
    assert captured_reviewers[0]["progress_stream"] is None
    assert captured_reviewers[0]["stream_stdout"] is False


def test_main_enables_review_command_logs_with_verbose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_reviewers: list[dict[str, Any]] = []

    class FakeApiClient(FakeClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__([])

    class CapturingSubprocessReviewer:
        def __init__(self, **kwargs: Any) -> None:
            captured_reviewers.append(kwargs)

    monkeypatch.setattr(cli, "WardnHubApiClient", FakeApiClient)
    monkeypatch.setattr(cli, "SubprocessReviewer", CapturingSubprocessReviewer)

    result = cli.main(["--token", "wardn_hub_test_token", "--once", "--verbose"])

    assert result == 0
    assert captured_reviewers[0]["progress_stream"] is sys.stdout
    assert captured_reviewers[0]["stream_stdout"] is False


def test_main_stream_review_output_implies_verbose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_reviewers: list[dict[str, Any]] = []

    class FakeApiClient(FakeClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__([])

    class CapturingSubprocessReviewer:
        def __init__(self, **kwargs: Any) -> None:
            captured_reviewers.append(kwargs)

    monkeypatch.setattr(cli, "WardnHubApiClient", FakeApiClient)
    monkeypatch.setattr(cli, "SubprocessReviewer", CapturingSubprocessReviewer)

    result = cli.main(["--token", "wardn_hub_test_token", "--once", "--stream-review-output"])

    assert result == 0
    assert captured_reviewers[0]["progress_stream"] is sys.stdout
    assert captured_reviewers[0]["stream_stdout"] is True


def test_api_client_sends_user_agent_header() -> None:
    captured: dict[str, str] = {}

    class FakeResponse:
        status = 200
        headers = {"content-type": "application/json"}

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok": true}'

    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        captured["user_agent"] = request.get_header("User-agent")
        captured["authorization"] = request.get_header("Authorization")
        assert timeout == 30
        return FakeResponse()

    client = cli.WardnHubApiClient(
        base_url="https://hub.example.com",
        token="wardn_hub_test_token",
        user_agent="WardnHubReviewCLI/edge-test",
        timeout_seconds=30,
    )

    with patch("urllib.request.urlopen", fake_urlopen):
        assert client.request("GET", "/auth/me") == {"ok": True}

    assert captured == {
        "authorization": "Bearer wardn_hub_test_token",
        "user_agent": "WardnHubReviewCLI/edge-test",
    }


def test_pending_submissions_filters_status_and_skips() -> None:
    submissions = [
        {"id": "a", "status": "submitted"},
        {"id": "b", "status": "draft"},
        {"id": "c", "status": "submitted"},
    ]

    assert cli.pending_submissions(submissions, skipped_ids={"a"}) == [
        {"id": "c", "status": "submitted"}
    ]


def test_validate_token_requires_review_role() -> None:
    class NonReviewerClient(FakeClient):
        def current_user(self) -> dict[str, Any]:
            user = super().current_user()
            user["is_superuser"] = False
            user["is_global_moderator"] = False
            return user

    with pytest.raises(cli.UserFacingError, match="superuser or global moderator"):
        cli.validate_token(NonReviewerClient())


def test_build_review_prompt_includes_context_and_no_secret_token() -> None:
    context = {
        "submission": submitted_submission(),
        "apiBaseUrl": "https://hub.example.com/api/v1",
        "apiTokenEnvironmentVariable": cli.TOKEN_ENV,
    }

    prompt = cli.build_review_prompt(context)

    assert "Validate one Wardn Hub MCP server version that is currently in review." in prompt
    assert "Wardn Hub API base URL: https://hub.example.com/api/v1" in prompt
    assert "io.github.example/weather" in prompt
    assert "wardn_hub_test_token" not in prompt
    assert "Read the upstream README and relevant docs/files" in prompt
    assert "Do not assume importer output is complete." in prompt
    assert "packages[].transport.args contains only the concrete default launch arguments" in prompt
    assert "Optional CLI flags/configurable arguments are represented" in prompt
    assert "Every documented environment variable is represented" in prompt
    assert "Do not mark a submission as passing if source review evidence is incomplete" in prompt
    assert "Decision: pass, needs fixes, or cannot validate" in prompt


def test_extract_suggested_rejection_message_from_fenced_section() -> None:
    findings = """Decision: needs fixes

Suggested rejection message:
```text
Please revise the metadata against upstream docs.
The package transport args include optional flags.
```

Suggested approval note: none; submission should not be approved.
"""

    assert cli.extract_suggested_rejection_message(findings) == (
        "Please revise the metadata against upstream docs.\n"
        "The package transport args include optional flags."
    )


def test_extract_suggested_rejection_message_ignores_none() -> None:
    findings = """Decision: pass

Suggested rejection message:
none

Suggested approval note:
Looks good.
"""

    assert cli.extract_suggested_rejection_message(findings) is None


def test_apply_decision_approve_publish_uses_api_without_llm() -> None:
    client = FakeClient()

    cli.apply_decision(
        client,
        "sub-1",
        "approve_publish",
        dry_run=False,
        stdin=StringIO(),
        stdout=StringIO(),
    )

    assert client.actions == [
        ("approve", "sub-1", None),
        ("publish", "sub-1", None),
    ]


def test_apply_decision_reject_reads_human_message() -> None:
    client = FakeClient()

    cli.apply_decision(
        client,
        "sub-1",
        "reject",
        dry_run=False,
        stdin=StringIO("Missing source review evidence.\n"),
        stdout=StringIO(),
    )

    assert client.actions == [
        ("reject", "sub-1", "Missing source review evidence."),
    ]


def test_apply_decision_reject_uses_suggested_message_without_prompting() -> None:
    client = FakeClient()
    stdout = StringIO()

    cli.apply_decision(
        client,
        "sub-1",
        "reject",
        dry_run=False,
        stdin=StringIO(),
        stdout=stdout,
        suggested_rejection_message="Use the generated rejection message.",
    )

    assert client.actions == [
        ("reject", "sub-1", "Use the generated rejection message."),
    ]
    assert "Using suggested rejection message" in stdout.getvalue()
    assert "Rejection message:" not in stdout.getvalue()


def test_review_loop_rejects_with_suggested_message() -> None:
    class RejectingReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            super().review(prompt, environment=environment)
            return """Decision: needs fixes

Suggested rejection message:
```text
Please fix the source review evidence.
```
"""

    client = FakeClient([submitted_submission()])
    reviewer = RejectingReviewer()
    stdout = StringIO()

    result = cli.review_loop(
        client=client,
        reviewer=reviewer,
        user=client.current_user(),
        max_reviews=None,
        once=True,
        dry_run=False,
        stdin=StringIO("r\n"),
        stdout=stdout,
    )

    assert result == 0
    assert client.actions == [
        ("reject", "sub-1", "Please fix the source review evidence."),
    ]
    assert "Rejection message:" not in stdout.getvalue()


def test_review_loop_skips_submission_for_current_run() -> None:
    client = FakeClient([submitted_submission()])
    reviewer = FakeReviewer()
    stdout = StringIO()

    result = cli.review_loop(
        client=client,
        reviewer=reviewer,
        user=client.current_user(),
        max_reviews=None,
        once=False,
        dry_run=False,
        stdin=StringIO("s\n"),
        stdout=stdout,
    )

    assert result == 0
    assert len(reviewer.prompts) == 1
    assert client.actions == []
    assert "Skipped sub-1" in stdout.getvalue()


def test_review_loop_continues_after_review_error() -> None:
    class FailingThenPassingReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            super().review(prompt, environment=environment)
            if len(self.prompts) == 1:
                raise cli.UserFacingError("review command timed out after 900 seconds")
            return "Decision: pass\n\nSuggested approval note:\nApproved."

    client = FakeClient(
        [
            submitted_submission_with_id("sub-1"),
            submitted_submission_with_id("sub-2"),
        ]
    )
    reviewer = FailingThenPassingReviewer()
    stdout = StringIO()

    result = cli.review_loop(
        client=client,
        reviewer=reviewer,
        user=client.current_user(),
        max_reviews=2,
        once=False,
        dry_run=False,
        stdin=StringIO("a\n"),
        stdout=stdout,
    )

    assert result == 1
    assert len(reviewer.prompts) == 2
    assert client.actions == [("approve", "sub-2", None)]
    output = stdout.getvalue()
    assert "Review failed for sub-1" in output
    assert "leaving submission unchanged" in output


def test_review_loop_once_stops_after_review_error() -> None:
    class FailingReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            super().review(prompt, environment=environment)
            raise cli.UserFacingError("review command timed out after 900 seconds")

    client = FakeClient([submitted_submission()])
    reviewer = FailingReviewer()
    stdout = StringIO()

    result = cli.review_loop(
        client=client,
        reviewer=reviewer,
        user=client.current_user(),
        max_reviews=None,
        once=True,
        dry_run=False,
        stdin=StringIO("a\n"),
        stdout=stdout,
    )

    assert result == 1
    assert len(reviewer.prompts) == 1
    assert client.actions == []
    assert "Review failed for sub-1" in stdout.getvalue()
