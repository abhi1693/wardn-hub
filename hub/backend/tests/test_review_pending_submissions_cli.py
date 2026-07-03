from __future__ import annotations

import json
import sys
import uuid
from io import StringIO
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError

from app.cli import review_pending_submissions as cli
from app.db import session as db_session
from app.modules.submissions import service as submissions_service
from app.modules.submissions.exceptions import SubmissionValidationError


class TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class FakeClient:
    def __init__(self, submissions: list[dict[str, Any]] | None = None) -> None:
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
        assert environment["WARDN_HUB_REVIEW_SUBMISSION_ID"].startswith("sub-")
        return "## Summary\nLooks structurally valid.\n\n## Recommended decision\napprove"


class FakeCodexWebSocket:
    def __init__(self, received: list[dict[str, Any]]) -> None:
        self.sent: list[dict[str, Any]] = []
        self._received = [json.dumps(item) for item in received]

    async def __aenter__(self) -> FakeCodexWebSocket:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def recv(self) -> str:
        if not self._received:
            raise AssertionError("fake Codex app-server websocket received no more messages")
        return self._received.pop(0)


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


def test_verbose_argument() -> None:
    default_args = cli.build_parser().parse_args([])
    args = cli.build_parser().parse_args(["--verbose"])

    assert default_args.verbose is False
    assert args.verbose is True


def test_codex_app_server_url_argument_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cli.CODEX_APP_SERVER_URL_ENV, "ws://127.0.0.1:41237")

    default_args = cli.build_parser().parse_args([])
    override_args = cli.build_parser().parse_args(
        ["--codex-app-server-url", "ws://127.0.0.1:5000"]
    )

    assert default_args.codex_app_server_url == "ws://127.0.0.1:41237"
    assert override_args.codex_app_server_url == "ws://127.0.0.1:5000"


def test_auto_reject_argument() -> None:
    default_args = cli.build_parser().parse_args([])
    args = cli.build_parser().parse_args(["--auto-reject"])

    assert default_args.auto_reject is False
    assert args.auto_reject is True


def test_auto_approve_argument() -> None:
    default_args = cli.build_parser().parse_args([])
    args = cli.build_parser().parse_args(["--auto-approve"])

    assert default_args.auto_approve is False
    assert args.auto_approve is True


def test_auto_publish_argument() -> None:
    default_args = cli.build_parser().parse_args([])
    args = cli.build_parser().parse_args(["--auto-publish"])

    assert default_args.auto_publish is False
    assert args.auto_publish is True


def test_targeted_non_interactive_arguments() -> None:
    default_args = cli.build_parser().parse_args([])
    args = cli.build_parser().parse_args(
        ["--submission-id", "sub-1", "--non-interactive"]
    )

    assert default_args.submission_id == ""
    assert default_args.non_interactive is False
    assert args.submission_id == "sub-1"
    assert args.non_interactive is True


def test_codex_app_server_reviewer_uses_one_ephemeral_turn_without_secrets() -> None:
    websocket = FakeCodexWebSocket(
        [
            {"id": 1, "result": {"userAgent": "codex-test"}},
            {
                "id": 2,
                "result": {
                    "thread": {"id": "thread-1"},
                    "model": "test-model",
                },
            },
            {
                "id": 3,
                "result": {
                    "turn": {
                        "id": "turn-1",
                        "items": [],
                        "itemsView": "notLoaded",
                        "status": "inProgress",
                        "error": None,
                    },
                },
            },
            {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "itemId": "message-1",
                    "delta": "Decision: pass",
                },
            },
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-1",
                    "turn": {
                        "id": "turn-1",
                        "items": [],
                        "itemsView": "notLoaded",
                        "status": "completed",
                        "error": None,
                    },
                },
            },
        ]
    )
    reviewer = cli.CodexAppServerReviewer(
        url="ws://127.0.0.1:41237",
        timeout_seconds=5,
        cwd=None,
        websocket_connect=lambda _url: websocket,
    )

    findings = reviewer.review(
        "review prompt",
        environment={"WARDN_HUB_TOKEN": "wardn_hub_test_token"},
    )

    assert findings == "Decision: pass"
    sent_json = json.dumps(websocket.sent)
    assert "wardn_hub_test_token" not in sent_json
    assert "system-secret" not in sent_json
    assert websocket.sent[1]["method"] == "thread/start"
    assert websocket.sent[1]["params"]["ephemeral"] is True
    assert websocket.sent[1]["params"]["approvalPolicy"] == "never"
    assert websocket.sent[1]["params"]["config"]["web_search"] == "live"
    assert "model" not in websocket.sent[1]["params"]
    assert websocket.sent[2]["method"] == "turn/start"
    assert websocket.sent[2]["params"]["threadId"] == "thread-1"
    assert websocket.sent[2]["params"]["input"][0]["text"] == "review prompt"
    assert "model" not in websocket.sent[2]["params"]
    assert "effort" not in websocket.sent[2]["params"]
    assert websocket.sent[2]["params"]["sandboxPolicy"] == {
        "type": "readOnly",
        "networkAccess": True,
    }


def test_codex_app_server_reviewer_uses_capability_token_header_only() -> None:
    websocket = FakeCodexWebSocket(
        [
            {"id": 1, "result": {"capabilities": {}}},
            {
                "id": 2,
                "result": {
                    "thread": {
                        "id": "thread-1",
                        "title": None,
                        "createdAt": "2026-07-03T00:00:00Z",
                        "updatedAt": "2026-07-03T00:00:00Z",
                    }
                },
            },
            {"id": 3, "result": {"turn": {"id": "turn-1"}}},
            {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "itemId": "message-1",
                    "delta": "Decision: pass",
                },
            },
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-1",
                    "turn": {
                        "id": "turn-1",
                        "items": [],
                        "itemsView": "notLoaded",
                        "status": "completed",
                        "error": None,
                    },
                },
            },
        ]
    )
    captured_connect: dict[str, Any] = {}

    def connect(url: str, **kwargs: Any) -> FakeCodexWebSocket:
        captured_connect["url"] = url
        captured_connect.update(kwargs)
        return websocket

    reviewer = cli.CodexAppServerReviewer(
        url="ws://127.0.0.1:41237",
        timeout_seconds=5,
        auth_token="codex-test-token",
        websocket_connect=connect,
    )

    findings = reviewer.review("review prompt", environment={})

    assert findings == "Decision: pass"
    assert captured_connect == {
        "url": "ws://127.0.0.1:41237",
        "additional_headers": {"Authorization": "Bearer codex-test-token"},
    }
    assert "codex-test-token" not in json.dumps(websocket.sent)


def test_main_uses_codex_app_server_without_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_reviewers: list[dict[str, Any]] = []

    class FakeDatabaseReviewClient(FakeClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__([])

    class CapturingCodexAppServerReviewer:
        def __init__(self, **kwargs: Any) -> None:
            captured_reviewers.append(kwargs)

    monkeypatch.setattr(cli, "WardnHubDatabaseReviewClient", FakeDatabaseReviewClient)
    monkeypatch.setattr(cli, "CodexAppServerReviewer", CapturingCodexAppServerReviewer)

    result = cli.main(
        [
            "--codex-app-server-url",
            "ws://127.0.0.1:41237",
            "--once",
            "--verbose",
        ]
    )

    assert result == 0
    assert captured_reviewers == [
        {
            "url": "ws://127.0.0.1:41237",
            "timeout_seconds": 900,
            "cwd": cli.Path.cwd(),
            "progress_stream": sys.stdout,
            "stream_output": True,
            "auth_token": "",
        }
    ]


def test_main_uses_database_queue_with_codex_app_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_created = False
    captured_reviewers: list[dict[str, Any]] = []

    class FakeDatabaseReviewClient(FakeClient):
        def __init__(self, **kwargs: Any) -> None:
            nonlocal client_created
            super().__init__([])
            assert kwargs == {}
            client_created = True

    class CapturingCodexAppServerReviewer:
        def __init__(self, **kwargs: Any) -> None:
            captured_reviewers.append(kwargs)

    monkeypatch.setattr(cli, "WardnHubDatabaseReviewClient", FakeDatabaseReviewClient)
    monkeypatch.setattr(cli, "CodexAppServerReviewer", CapturingCodexAppServerReviewer)

    result = cli.main(
        [
            "--codex-app-server-url",
            "ws://127.0.0.1:41237",
            "--once",
        ]
    )

    assert result == 0
    assert client_created is True
    assert captured_reviewers[0]["url"] == "ws://127.0.0.1:41237"
    assert captured_reviewers[0]["auth_token"] == ""


def test_main_passes_codex_app_server_auth_token_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_reviewers: list[dict[str, Any]] = []

    class FakeDatabaseReviewClient(FakeClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__([])

    class CapturingCodexAppServerReviewer:
        def __init__(self, **kwargs: Any) -> None:
            captured_reviewers.append(kwargs)

    monkeypatch.setenv(cli.CODEX_APP_SERVER_AUTH_TOKEN_ENV, " test-token ")
    monkeypatch.setattr(cli, "WardnHubDatabaseReviewClient", FakeDatabaseReviewClient)
    monkeypatch.setattr(cli, "CodexAppServerReviewer", CapturingCodexAppServerReviewer)

    result = cli.main(
        [
            "--codex-app-server-url",
            "ws://127.0.0.1:41237",
            "--once",
        ]
    )

    assert result == 0
    assert captured_reviewers[0]["auth_token"] == "test-token"


def test_main_requires_app_server_without_explicit_review_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli.main(["--once"])

    assert result == 1
    assert "Codex app-server review is required" in capsys.readouterr().err


def transient_database_error() -> DBAPIError:
    return DBAPIError(
        "select 1",
        {},
        Exception(
            "asyncpg.exceptions.ConnectionDoesNotExistError: "
            "connection was closed in the middle of operation"
        ),
    )


def test_transient_database_disconnect_detection() -> None:
    assert cli.is_transient_database_disconnect(transient_database_error()) is True
    assert cli.is_transient_database_disconnect(ValueError("connection was closed")) is False


def test_database_review_client_retries_read_only_transient_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSession:
        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def rollback(self) -> None:
            return None

    def fake_session_local() -> FakeSession:
        return FakeSession()

    attempts = 0

    async def operation(_session: object) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise transient_database_error()
        return "ok"

    monkeypatch.setattr(db_session, "AsyncSessionLocal", fake_session_local)
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)
    client = cli.WardnHubDatabaseReviewClient()
    try:
        assert client._run_database_operation(operation) == "ok"
    finally:
        client._loop.close()
    assert attempts == 2


def test_database_review_client_does_not_retry_commit_transient_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSession:
        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def rollback(self) -> None:
            return None

    def fake_session_local() -> FakeSession:
        return FakeSession()

    attempts = 0

    async def operation(_session: object) -> str:
        nonlocal attempts
        attempts += 1
        raise transient_database_error()

    monkeypatch.setattr(db_session, "AsyncSessionLocal", fake_session_local)
    client = cli.WardnHubDatabaseReviewClient()
    try:
        with pytest.raises(DBAPIError):
            client._run_database_operation(operation, commit=True)
    finally:
        client._loop.close()
    assert attempts == 1


def test_pending_submissions_filters_status_and_skips() -> None:
    submissions = [
        {"id": "a", "status": "submitted"},
        {"id": "b", "status": "draft"},
        {"id": "c", "status": "submitted"},
    ]

    assert cli.pending_submissions(submissions, skipped_ids={"a"}) == [
        {"id": "c", "status": "submitted"}
    ]


def test_pending_submissions_orders_oldest_submitted_first() -> None:
    submissions = [
        {"id": "newest", "status": "submitted", "submittedAt": "2026-06-27T12:00:00Z"},
        {"id": "draft", "status": "draft", "submittedAt": "2026-06-20T12:00:00Z"},
        {"id": "oldest", "status": "submitted", "submittedAt": "2026-06-25T12:00:00Z"},
        {"id": "middle", "status": "submitted", "submittedAt": "2026-06-26T12:00:00Z"},
    ]

    pending_ids = [
        submission["id"]
        for submission in cli.pending_submissions(submissions, skipped_ids=set())
    ]

    assert pending_ids == [
        "oldest",
        "middle",
        "newest",
    ]


def test_build_review_prompt_includes_context_and_no_secret_token() -> None:
    context = {"submission": submitted_submission()}

    prompt = cli.build_review_prompt(context)

    assert "Validate one Wardn Hub MCP server version that is currently in review." in prompt
    assert "System review mode:" in prompt
    assert "Wardn Hub submission JSON snapshot" in prompt
    assert "Submitted MCP server model JSON from to_json_dict()" in prompt
    assert '"serverJson"' in prompt
    assert "io.github.example/weather" in prompt
    assert "Do not call Wardn Hub API endpoints." in prompt
    assert "WARDN_HUB_TOKEN" not in prompt
    assert "WARDN_HUB_SYSTEM_REVIEW_SECRET" not in prompt
    assert "Use the Wardn Hub submission JSON snapshot for submission ID" in prompt
    assert "Read the Submitted MCP server model JSON from to_json_dict()" in prompt
    assert "Read the upstream README and relevant docs/files" in prompt
    assert "Do not assume importer output is complete." in prompt
    assert (
        'If submissionType is "new_server", serverJson.version is the Wardn registry version'
        in prompt
    )
    assert "packages[].transport.args contains only the concrete default launch arguments" in prompt
    assert "Optional CLI flags/configurable arguments are represented" in prompt
    assert "Every documented environment variable is represented" in prompt
    assert "Do not mark a submission as passing if source review evidence is incomplete" in prompt
    assert "Decision: pass, needs fixes, or cannot validate" in prompt
    assert "Call GET /submissions" not in prompt


def test_submitted_mcp_server_model_json_uses_schema_serializer() -> None:
    submission = submitted_submission()
    submission["serverJson"] = {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": "io.github.example/weather",
        "title": "Weather",
        "description": "Weather tools.",
        "documentation": "# Weather",
        "version": "1.0.0",
        "websiteUrl": "https://example.com/weather",
        "packages": [{"registryType": "npm", "identifier": "@example/weather"}],
        "_meta": {"categories": ["developer-tools"]},
    }

    serialized = cli.submitted_mcp_server_model_json(submission)

    assert serialized["websiteUrl"] == "https://example.com/weather"
    assert serialized["packages"][0]["registryType"] == "npm"
    assert "website_url" not in serialized


def test_review_loop_sets_only_submission_context_environment() -> None:
    class EnvironmentCheckingReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            self.prompts.append(prompt)
            assert "WARDN_HUB_TOKEN" not in environment
            assert "WARDN_HUB_SYSTEM_REVIEW_SECRET" not in environment
            assert "WARDN_HUB_API_BASE_URL" not in environment
            assert environment["WARDN_HUB_REVIEW_SUBMISSION_ID"] == "sub-1"
            return "Decision: pass\n\nSuggested approval note:\nApproved."

    client = FakeClient([submitted_submission()])
    reviewer = EnvironmentCheckingReviewer()

    result = cli.review_loop(
        client=client,
        reviewer=reviewer,
        user={"_wardnHubCanPublish": False},
        max_reviews=None,
        once=True,
        dry_run=False,
        auto_reject=False,
        auto_approve=True,
        stdin=StringIO(),
        stdout=StringIO(),
        non_interactive=True,
    )

    assert result == 0
    assert client.actions == [("approve", "sub-1", None)]
    assert "System review mode:" in reviewer.prompts[0]


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


def test_extract_review_decision() -> None:
    assert cli.extract_review_decision("Decision: pass") == "pass"
    assert cli.extract_review_decision("Decision: needs fixes") == "needs_fixes"
    assert cli.extract_review_decision("Decision: cannot validate") == "cannot_validate"
    assert cli.extract_review_decision("Decision: cannot determine") == "cannot_validate"
    assert cli.extract_review_decision("Decision: uncertain") == "cannot_validate"
    assert cli.extract_review_decision("Decision: skip") == "skip"
    assert cli.extract_review_decision("Decision: leave unchanged") == "skip"
    assert cli.extract_review_decision("Decision: reject") == "reject"
    assert cli.extract_review_decision("No decision here") is None


def test_should_auto_reject_does_not_reject_uncertain_decisions() -> None:
    assert cli.should_auto_reject("Decision: needs fixes") is True
    assert cli.should_auto_reject("Decision: reject") is True
    assert cli.should_auto_reject("Decision: cannot validate") is False
    assert cli.should_auto_reject("Decision: cannot determine") is False


def test_should_auto_approve_only_passes_clean_pass_decision() -> None:
    assert cli.should_auto_approve("Decision: pass") is True
    assert cli.should_auto_approve("Decision: needs fixes") is False
    assert cli.should_auto_approve("Decision: cannot validate") is False


def test_should_auto_skip_uncertain_decisions() -> None:
    assert cli.should_auto_skip("Decision: cannot validate") is True
    assert cli.should_auto_skip("Decision: cannot determine") is True
    assert cli.should_auto_skip("Decision: skip") is True
    assert cli.should_auto_skip("Decision: pass") is False


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
        auto_reject=False,
        auto_approve=False,
        stdin=StringIO("r\n"),
        stdout=stdout,
    )

    assert result == 0
    assert client.actions == [
        ("reject", "sub-1", "Please fix the source review evidence."),
    ]
    assert "Rejection message:" not in stdout.getvalue()


def test_review_loop_auto_rejects_llm_rejection_with_suggested_message() -> None:
    class RejectingReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            super().review(prompt, environment=environment)
            return """Decision: needs fixes

Suggested rejection message:
Please add missing package transport metadata.
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
        auto_reject=True,
        auto_approve=False,
        stdin=StringIO(),
        stdout=stdout,
    )

    assert result == 0
    assert client.actions == [
        ("reject", "sub-1", "Please add missing package transport metadata."),
    ]
    output = stdout.getvalue()
    assert "Auto-rejecting with suggested rejection message" in output
    assert "Decision (" not in output


def test_review_loop_skips_uncertain_llm_decision_without_prompt_or_action() -> None:
    class UncertainReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            super().review(prompt, environment=environment)
            return """Decision: cannot validate

Findings grouped by severity:
Source repository was unavailable, so no safe approval or rejection decision can be made.

Suggested rejection message:
none
"""

    client = FakeClient([submitted_submission()])
    reviewer = UncertainReviewer()
    stdout = StringIO()

    result = cli.review_loop(
        client=client,
        reviewer=reviewer,
        user=client.current_user(),
        max_reviews=None,
        once=True,
        dry_run=False,
        auto_reject=True,
        auto_approve=True,
        stdin=StringIO(),
        stdout=stdout,
    )

    assert result == 0
    assert client.actions == []
    output = stdout.getvalue()
    assert "could not determine a safe action" in output
    assert "skipping it for this run" in output
    assert "Auto-rejecting" not in output
    assert "Decision (" not in output


def test_review_loop_targets_exact_submission_id() -> None:
    client = FakeClient(
        [
            submitted_submission_with_id("sub-1"),
            submitted_submission_with_id("sub-2"),
        ]
    )
    reviewer = FakeReviewer()
    stdout = StringIO()

    result = cli.review_loop(
        client=client,
        reviewer=reviewer,
        user=client.current_user(),
        max_reviews=None,
        once=True,
        dry_run=False,
        auto_reject=False,
        auto_approve=False,
        stdin=StringIO("s\n"),
        stdout=stdout,
        submission_id="sub-2",
    )

    assert result == 0
    assert len(reviewer.prompts) == 1
    assert "sub-2" in reviewer.prompts[0]
    assert "sub-1" not in reviewer.prompts[0]
    assert "Skipped sub-2" in stdout.getvalue()


def test_review_loop_skips_missing_exact_submission_id() -> None:
    client = FakeClient([])
    reviewer = FakeReviewer()
    stdout = StringIO()

    result = cli.review_loop(
        client=client,
        reviewer=reviewer,
        user=client.current_user(),
        max_reviews=None,
        once=True,
        dry_run=False,
        auto_reject=True,
        auto_approve=True,
        stdin=StringIO(),
        stdout=stdout,
        submission_id="missing-sub",
        non_interactive=True,
    )

    assert result == 0
    assert reviewer.prompts == []
    assert "Submission missing-sub is not currently submitted for review." in stdout.getvalue()


def test_review_loop_non_interactive_skips_without_prompt() -> None:
    class NeedsHumanReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            super().review(prompt, environment=environment)
            return """Decision: needs fixes

Suggested rejection message:
none
"""

    client = FakeClient([submitted_submission()])
    reviewer = NeedsHumanReviewer()
    stdout = StringIO()

    result = cli.review_loop(
        client=client,
        reviewer=reviewer,
        user=client.current_user(),
        max_reviews=None,
        once=True,
        dry_run=False,
        auto_reject=True,
        auto_approve=True,
        stdin=StringIO(),
        stdout=stdout,
        non_interactive=True,
    )

    assert result == 0
    assert client.actions == []
    output = stdout.getvalue()
    assert "leaving submission unchanged and skipping it for this run" in output
    assert "Decision (" not in output


def test_review_loop_auto_reject_falls_back_without_suggested_message() -> None:
    class RejectingReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            super().review(prompt, environment=environment)
            return """Decision: needs fixes

Suggested rejection message:
none
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
        auto_reject=True,
        auto_approve=False,
        stdin=StringIO("s\n"),
        stdout=stdout,
    )

    assert result == 0
    assert client.actions == []
    output = stdout.getvalue()
    assert "Auto-reject requested, but no suggested rejection message was found" in output
    assert "Skipped sub-1" in output


def test_review_loop_auto_approves_llm_pass_without_publishing() -> None:
    class PassingReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            super().review(prompt, environment=environment)
            return """Decision: pass

Suggested approval note:
Approved.
"""

    client = FakeClient([submitted_submission()])
    user = client.current_user()
    user["_wardnHubCanPublish"] = True
    reviewer = PassingReviewer()
    stdout = StringIO()

    result = cli.review_loop(
        client=client,
        reviewer=reviewer,
        user=user,
        max_reviews=None,
        once=True,
        dry_run=False,
        auto_reject=False,
        auto_approve=True,
        stdin=StringIO(),
        stdout=stdout,
    )

    assert result == 0
    assert client.actions == [("approve", "sub-1", None)]
    output = stdout.getvalue()
    assert "Auto-approving LLM pass decision." in output
    assert "Decision (" not in output


def test_review_loop_auto_publishes_llm_pass_with_publish_access() -> None:
    class PassingReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            super().review(prompt, environment=environment)
            return """Decision: pass

Suggested approval note:
Approved.
"""

    client = FakeClient([submitted_submission()])
    user = client.current_user()
    user["_wardnHubCanPublish"] = True
    reviewer = PassingReviewer()
    stdout = StringIO()

    result = cli.review_loop(
        client=client,
        reviewer=reviewer,
        user=user,
        max_reviews=None,
        once=True,
        dry_run=False,
        auto_reject=False,
        auto_approve=False,
        stdin=StringIO(),
        stdout=stdout,
        auto_publish=True,
    )

    assert result == 0
    assert client.actions == [
        ("approve", "sub-1", None),
        ("publish", "sub-1", None),
    ]
    output = stdout.getvalue()
    assert "Auto-publishing LLM pass decision." in output
    assert "Approved and published sub-1." in output
    assert "Decision (" not in output


def test_review_loop_auto_publish_leaves_pass_without_publish_access() -> None:
    class PassingReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            super().review(prompt, environment=environment)
            return """Decision: pass

Suggested approval note:
Approved.
"""

    client = FakeClient([submitted_submission()])
    user = client.current_user()
    user["_wardnHubCanPublish"] = False
    reviewer = PassingReviewer()
    stdout = StringIO()

    result = cli.review_loop(
        client=client,
        reviewer=reviewer,
        user=user,
        max_reviews=None,
        once=True,
        dry_run=False,
        auto_reject=False,
        auto_approve=False,
        stdin=StringIO(),
        stdout=stdout,
        non_interactive=True,
        auto_publish=True,
    )

    assert result == 0
    assert client.actions == []
    output = stdout.getvalue()
    assert "Auto-publish requested" in output
    assert "does not have publish access" in output
    assert "Decision (" not in output


def test_review_loop_auto_approve_leaves_non_pass_for_manual_decision() -> None:
    class RejectingReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            super().review(prompt, environment=environment)
            return """Decision: needs fixes

Suggested rejection message:
Please fix the metadata.
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
        auto_reject=False,
        auto_approve=True,
        stdin=StringIO("s\n"),
        stdout=stdout,
    )

    assert result == 0
    assert client.actions == []
    output = stdout.getvalue()
    assert "Auto-approving" not in output
    assert "Skipped sub-1" in output


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
        auto_reject=False,
        auto_approve=False,
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
                raise cli.UserFacingError("Codex app-server review timed out after 900 seconds")
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
        auto_reject=False,
        auto_approve=False,
        stdin=StringIO("a\n"),
        stdout=stdout,
    )

    assert result == 1
    assert len(reviewer.prompts) == 2
    assert client.actions == [("approve", "sub-2", None)]
    output = stdout.getvalue()
    assert "Review failed for sub-1" in output
    assert "leaving submission unchanged" in output


def test_review_loop_continues_after_action_error() -> None:
    class ActionFailingClient(FakeClient):
        def reject_submission(self, submission_id: str, message: str) -> dict[str, Any]:
            raise cli.UserFacingError("timed out after 30 seconds reading Wardn Hub API response")

    class RejectingReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            super().review(prompt, environment=environment)
            if len(self.prompts) == 1:
                return """Decision: needs fixes

Suggested rejection message:
Please fix the metadata.
"""
            return "Decision: pass\n\nSuggested approval note:\nApproved."

    client = ActionFailingClient(
        [
            submitted_submission_with_id("sub-1"),
            submitted_submission_with_id("sub-2"),
        ]
    )
    reviewer = RejectingReviewer()
    stdout = StringIO()

    result = cli.review_loop(
        client=client,
        reviewer=reviewer,
        user=client.current_user(),
        max_reviews=2,
        once=False,
        dry_run=False,
        auto_reject=False,
        auto_approve=False,
        stdin=StringIO("r\na\n"),
        stdout=stdout,
    )

    assert result == 1
    assert len(reviewer.prompts) == 2
    assert client.actions == [("approve", "sub-2", None)]
    output = stdout.getvalue()
    assert "Action failed for sub-1" in output
    assert "skipping it for this run" in output


def test_database_review_client_wraps_submission_approval_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def approve_submission_by_system(_session: object, _submission_id: uuid.UUID) -> None:
        raise SubmissionValidationError("server already exists; submit a new version")

    client = cli.WardnHubDatabaseReviewClient()

    def run_database_operation(operation: Any, *, commit: bool = False) -> Any:
        assert commit is True

        async def run() -> Any:
            return await operation(object())

        return client._loop.run_until_complete(run())

    monkeypatch.setattr(
        submissions_service,
        "approve_submission_by_system",
        approve_submission_by_system,
    )
    monkeypatch.setattr(client, "_run_database_operation", run_database_operation)

    with pytest.raises(
        cli.UserFacingError,
        match="Unable to approve submission: server already exists; submit a new version",
    ):
        client.approve_submission(str(uuid.uuid4()))


def test_review_loop_once_stops_after_review_error() -> None:
    class FailingReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            super().review(prompt, environment=environment)
            raise cli.UserFacingError("Codex app-server review timed out after 900 seconds")

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
        auto_reject=False,
        auto_approve=False,
        stdin=StringIO("a\n"),
        stdout=stdout,
    )

    assert result == 1
    assert len(reviewer.prompts) == 1
    assert client.actions == []
    assert "Review failed for sub-1" in stdout.getvalue()
