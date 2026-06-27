from __future__ import annotations

from io import StringIO
from typing import Any
from unittest.mock import patch

import pytest

from app.cli import review_pending_submissions as cli


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

    assert args.review_command == "codex exec --sandbox read-only --skip-git-repo-check -"
    assert "--ask-for-approval" not in args.review_command


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
        "apiTokenEnvironmentVariable": cli.TOKEN_ENV,
    }

    prompt = cli.build_review_prompt(context)

    assert "Wardn Hub MCP server submission" in prompt
    assert "io.github.example/weather" in prompt
    assert "wardn_hub_test_token" not in prompt
    assert "Do not call POST, PUT, PATCH, or DELETE" in prompt


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
