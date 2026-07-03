from __future__ import annotations

import json
from io import StringIO
from typing import Any

from app.cli import fix_rejected_submissions as cli


class FakeClient:
    def __init__(self, submissions: list[dict[str, Any]] | None = None) -> None:
        self.submissions = submissions or []
        self.fixed: list[tuple[str, dict[str, Any]]] = []

    def list_submissions(self) -> list[dict[str, Any]]:
        return self.submissions

    def get_submission(self, submission_id: str) -> dict[str, Any]:
        for submission in self.submissions:
            if submission["id"] == submission_id:
                return submission
        raise AssertionError(f"unknown submission {submission_id}")

    def fix_submission(self, submission_id: str, server_json: dict[str, Any]) -> dict[str, Any]:
        self.fixed.append((submission_id, server_json))
        for submission in self.submissions:
            if submission["id"] == submission_id:
                submission["serverJson"] = server_json
                submission["name"] = server_json["name"]
                submission["version"] = server_json["version"]
                submission["status"] = "submitted"
                return submission
        raise AssertionError(f"unknown submission {submission_id}")


class FakeReviewer:
    def __init__(self, server_json: dict[str, Any] | None = None) -> None:
        self.server_json = server_json or complete_server_json()
        self.prompts: list[str] = []
        self.environments: list[dict[str, str]] = []

    def review(self, prompt: str, *, environment: dict[str, str]) -> str:
        self.prompts.append(prompt)
        self.environments.append(environment)
        return (
            "Decision: fixed\n\n"
            "Updated serverJson:\n"
            "```json\n"
            f"{json.dumps(self.server_json)}\n"
            "```"
        )


def complete_server_json(version: str = "1.0.0") -> dict[str, Any]:
    return {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": "io.github.example/weather",
        "title": "Weather",
        "description": "Weather tools.",
        "documentation": "# Weather\n\nUse this server for forecast tools.",
        "version": version,
        "websiteUrl": "https://github.com/example/weather",
        "repository": {
            "type": "git",
            "source": "github",
            "url": "https://github.com/example/weather",
        },
        "packages": [
            {
                "registryType": "npm",
                "identifier": "@example/weather",
                "version": version,
                "transport": {"type": "stdio", "command": "npx", "args": []},
            }
        ],
        "_meta": {
            "categories": ["developer-tools"],
            "sourceReview": {
                "llm": {
                    "filesRead": ["https://github.com/example/weather/README.md"],
                    "installCommands": ["npx @example/weather"],
                    "commandArguments": [],
                    "environmentVariables": [],
                    "prerequisites": [],
                    "capabilitiesReviewed": True,
                    "limitationsReviewed": True,
                    "unknowns": [],
                }
            },
        },
    }


def rejected_submission(
    *,
    submission_id: str = "sub-1",
    status: str = "rejected",
    updated_at: str = "2026-06-28T10:00:00Z",
) -> dict[str, Any]:
    return {
        "id": submission_id,
        "name": "io.github.example/weather",
        "version": "1.0.0",
        "status": status,
        "submissionType": "new_server",
        "ownerUserId": "superuser-1",
        "ownerOrganizationId": None,
        "rejectionMessage": "Add complete source review evidence.",
        "serverJson": complete_server_json(),
        "validationResult": {"status": "failed", "checks": []},
        "updatedAt": updated_at,
    }


def test_build_fix_prompt_uses_db_context_without_token_or_api_instructions() -> None:
    client = FakeClient([rejected_submission()])
    context = cli.build_fix_context(client, client.submissions[0])

    prompt = cli.build_fix_prompt(context)

    assert "Fix this Wardn Hub draft or rejected MCP server submission" in prompt
    assert "Submission ID: sub-1" in prompt
    assert "Current submit/review feedback: Add complete source review evidence." in prompt
    assert "Wardn Hub submission JSON snapshot" in prompt
    assert "Submitted MCP server model JSON from to_json_dict()" in prompt
    assert "Do not call Wardn Hub API endpoints." in prompt
    assert "The database fix controller will apply your returned serverJson" in prompt
    assert 'If submissionType is "new_server", keep serverJson.version' in prompt
    assert "Updated serverJson:" in prompt
    assert "WARDN_HUB_TOKEN" not in prompt
    assert "GET /submissions" not in prompt
    assert "PUT /submissions" not in prompt


def test_fix_loop_applies_updated_server_json_and_submits() -> None:
    client = FakeClient(
        [
            rejected_submission(submission_id="newer", updated_at="2026-06-29T10:00:00Z"),
            rejected_submission(submission_id="oldest", updated_at="2026-06-28T10:00:00Z"),
        ]
    )
    reviewer = FakeReviewer()
    stdout = StringIO()

    result = cli.fix_loop(
        client=client,
        reviewer=reviewer,
        user={"id": "database"},
        max_fixes=None,
        once=True,
        dry_run=False,
        stdout=stdout,
    )

    assert result == 0
    assert len(reviewer.prompts) == 1
    assert "Submission ID: oldest" in reviewer.prompts[0]
    assert reviewer.environments[0]["WARDN_HUB_FIX_SUBMISSION_ID"] == "oldest"
    assert client.fixed[0][0] == "oldest"
    assert client.get_submission("oldest")["status"] == "submitted"
    assert "Submitted oldest for review." in stdout.getvalue()


def test_fix_loop_preserves_new_server_registry_version() -> None:
    server_json = complete_server_json(version="2026.5.54")
    server_json["packages"][0]["version"] = "2026.5.54"
    client = FakeClient([rejected_submission()])
    reviewer = FakeReviewer(server_json)
    stdout = StringIO()

    result = cli.fix_loop(
        client=client,
        reviewer=reviewer,
        user={"id": "database"},
        max_fixes=None,
        once=True,
        dry_run=False,
        stdout=stdout,
    )

    assert result == 0
    applied_server_json = client.fixed[0][1]
    assert applied_server_json["version"] == "1.0.0"
    assert applied_server_json["packages"][0]["version"] == "2026.5.54"
    assert client.get_submission("sub-1")["version"] == "1.0.0"


def test_fix_loop_skips_cannot_fix_decision() -> None:
    class CannotFixReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            self.prompts.append(prompt)
            self.environments.append(environment)
            return "Decision: cannot fix\n\nMissing official repository URL."

    client = FakeClient([rejected_submission()])
    reviewer = CannotFixReviewer()
    stdout = StringIO()

    result = cli.fix_loop(
        client=client,
        reviewer=reviewer,
        user={"id": "database"},
        max_fixes=None,
        once=True,
        dry_run=False,
        stdout=stdout,
    )

    assert result == 0
    assert client.fixed == []
    assert "Reviewer could not fix sub-1" in stdout.getvalue()


def test_fix_loop_reports_failure_when_llm_omits_server_json() -> None:
    class MissingJsonReviewer(FakeReviewer):
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            self.prompts.append(prompt)
            self.environments.append(environment)
            return "Decision: fixed\n\nSummary: fixed it"

    client = FakeClient([rejected_submission()])
    reviewer = MissingJsonReviewer()
    stdout = StringIO()

    result = cli.fix_loop(
        client=client,
        reviewer=reviewer,
        user={"id": "database"},
        max_fixes=None,
        once=True,
        dry_run=False,
        stdout=stdout,
    )

    assert result == 1
    assert client.fixed == []
    assert "LLM did not return Updated serverJson" in stdout.getvalue()


def test_dry_run_prints_prompt_without_running_reviewer() -> None:
    client = FakeClient([rejected_submission()])
    reviewer = FakeReviewer()
    stdout = StringIO()

    result = cli.fix_loop(
        client=client,
        reviewer=reviewer,
        user={"id": "database"},
        max_fixes=None,
        once=True,
        dry_run=True,
        stdout=stdout,
    )

    assert result == 0
    assert reviewer.prompts == []
    assert client.fixed == []
    assert "Fix this Wardn Hub draft or rejected MCP server submission" in stdout.getvalue()


def test_extract_updated_server_json_reads_nested_fenced_json() -> None:
    server_json = complete_server_json()
    findings = (
        "Decision: fixed\n"
        "Updated serverJson:\n"
        "```json\n"
        f"{json.dumps(server_json, indent=2)}\n"
        "```"
    )

    assert cli.extract_updated_server_json(findings) == server_json


def test_extract_updated_server_json_allows_markdown_fences_inside_json_string() -> None:
    server_json = complete_server_json()
    server_json["documentation"] = (
        "## Installation\n\n"
        "```bash\n"
        "npx @example/weather\n"
        "```\n\n"
        "```json\n"
        '{"mcpServers":{"weather":{"command":"npx"}}}\n'
        "```"
    )
    findings = (
        "Decision: fixed\n"
        "Updated serverJson:\n"
        "```json\n"
        f"{json.dumps(server_json, indent=2)}\n"
        "```"
    )

    assert cli.extract_updated_server_json(findings) == server_json


def test_parser_uses_app_server_defaults() -> None:
    args = cli.build_parser().parse_args(["--submission-id", "sub-1", "--dry-run"])

    assert args.submission_id == "sub-1"
    assert args.dry_run is True
    assert hasattr(args, "codex_app_server_url")
    assert not hasattr(args, "review_command")
