from __future__ import annotations

from io import StringIO
from typing import Any

from app.cli import fix_rejected_submissions as cli


class FakeClient:
    def __init__(self, submissions: list[dict[str, Any]] | None = None) -> None:
        self.token = "wardn_hub_test_token"
        self.base_url = "http://localhost:8000/api/v1"
        self.submissions = submissions or []

    def current_user(self) -> dict[str, Any]:
        return {
            "id": "user-1",
            "email": "owner@example.com",
            "display_name": "Owner",
            "is_active": True,
            "is_superuser": False,
            "is_global_moderator": False,
        }

    def list_submissions(self) -> list[dict[str, Any]]:
        return self.submissions

    def get_submission(self, submission_id: str) -> dict[str, Any]:
        for submission in self.submissions:
            if submission["id"] == submission_id:
                return submission
        raise AssertionError(f"unknown submission {submission_id}")


class FakeReviewer:
    def __init__(self, client: FakeClient, *, final_status: str = "submitted") -> None:
        self.client = client
        self.final_status = final_status
        self.prompts: list[str] = []
        self.environments: list[dict[str, str]] = []

    def review(self, prompt: str, *, environment: dict[str, str]) -> str:
        self.prompts.append(prompt)
        self.environments.append(environment)
        submission_id = environment["WARDN_HUB_FIX_SUBMISSION_ID"]
        for submission in self.client.submissions:
            if submission["id"] == submission_id:
                submission["status"] = self.final_status
                break
        return "final status updated"


def rejected_submission(
    *,
    submission_id: str = "sub-1",
    owner_user_id: str = "user-1",
    owner_organization_id: str | None = None,
    status: str = "rejected",
) -> dict[str, Any]:
    return {
        "id": submission_id,
        "name": "io.github.example/weather",
        "version": "1.0.0",
        "status": status,
        "submissionType": "new_server",
        "ownerUserId": owner_user_id,
        "ownerOrganizationId": owner_organization_id,
        "rejectionMessage": "Add complete source review evidence.",
        "serverJson": {
            "name": "io.github.example/weather",
            "version": "1.0.0",
            "description": "Weather tools.",
            "repository": {
                "type": "git",
                "source": "github",
                "url": "https://github.com/example/weather",
            },
            "packages": [{"registryType": "npm", "identifier": "@example/weather"}],
            "_meta": {"categories": ["developer-tools"]},
        },
        "validationResult": {"status": "failed", "checks": []},
        "updatedAt": "2026-06-28T10:00:00Z",
    }


def test_build_fix_prompt_copies_frontend_repair_instructions_without_token() -> None:
    client = FakeClient([rejected_submission()])
    context = cli.build_fix_context(client, client.submissions[0], user_id="user-1")

    prompt = cli.build_fix_prompt(context)

    assert "Fix this Wardn Hub draft or rejected submission" in prompt
    assert "Submission ID: sub-1" in prompt
    assert "Expected ownerUserId for this token: user-1" in prompt
    assert "Current submit/review feedback: Add complete source review evidence." in prompt
    assert "Fetch the submission with GET /submissions/sub-1" in prompt
    assert 'status "draft" or "rejected"' in prompt
    assert "Update the same submission with PUT /submissions/sub-1" in prompt
    assert "Retry POST /submissions/sub-1/submit" in prompt
    assert "Do not create a new submission" in prompt
    assert "Do not update submissions owned by any other user or organization." in prompt
    assert "sourceReview.llm.filesRead" in prompt
    assert "Package argument rules:" in prompt
    assert "wardn_hub_test_token" not in prompt


def test_fix_loop_processes_draft_or_rejected_submissions_owned_by_current_user() -> None:
    client = FakeClient(
        [
            rejected_submission(submission_id="other-user", owner_user_id="user-2"),
            rejected_submission(submission_id="org-owned", owner_organization_id="org-1"),
            rejected_submission(submission_id="approved", status="approved"),
            rejected_submission(submission_id="draft", status="draft"),
            rejected_submission(submission_id="owned"),
        ]
    )
    reviewer = FakeReviewer(client)
    stdout = StringIO()

    result = cli.fix_loop(
        client=client,
        reviewer=reviewer,
        user=client.current_user(),
        max_fixes=None,
        once=True,
        dry_run=False,
        stdout=stdout,
    )

    assert result == 0
    assert len(reviewer.prompts) == 1
    assert "Submission ID: draft" in reviewer.prompts[0]
    output = stdout.getvalue()
    assert "owned by different user user-2" in output
    assert "owned by organization org-1" in output
    assert "Submitted draft for review." in output


def test_fix_loop_processes_rejected_after_drafts() -> None:
    client = FakeClient(
        [
            rejected_submission(submission_id="draft", status="draft"),
            rejected_submission(submission_id="owned"),
        ]
    )
    reviewer = FakeReviewer(client)
    stdout = StringIO()

    result = cli.fix_loop(
        client=client,
        reviewer=reviewer,
        user=client.current_user(),
        max_fixes=None,
        once=False,
        dry_run=False,
        stdout=stdout,
    )

    assert result == 0
    assert len(reviewer.prompts) == 2
    assert "Submission ID: draft" in reviewer.prompts[0]
    assert "Submission ID: owned" in reviewer.prompts[1]
    assert "fixed=2" in stdout.getvalue()


def test_fix_loop_skips_exact_submission_owned_by_different_user() -> None:
    client = FakeClient([rejected_submission(owner_user_id="user-2")])
    reviewer = FakeReviewer(client)
    stdout = StringIO()

    result = cli.fix_loop(
        client=client,
        reviewer=reviewer,
        user=client.current_user(),
        max_fixes=None,
        once=True,
        dry_run=False,
        stdout=stdout,
        submission_id="sub-1",
    )

    assert result == 0
    assert reviewer.prompts == []
    assert "owned by different user user-2" in stdout.getvalue()


def test_fix_loop_reports_failure_when_reviewer_does_not_submit() -> None:
    client = FakeClient([rejected_submission()])
    reviewer = FakeReviewer(client, final_status="draft")
    stdout = StringIO()

    result = cli.fix_loop(
        client=client,
        reviewer=reviewer,
        user=client.current_user(),
        max_fixes=None,
        once=True,
        dry_run=False,
        stdout=stdout,
    )

    assert result == 1
    assert "final status is draft" in stdout.getvalue()
    assert "failed=1" in stdout.getvalue()


def test_dry_run_prints_prompt_without_running_reviewer() -> None:
    client = FakeClient([rejected_submission()])
    reviewer = FakeReviewer(client)
    stdout = StringIO()

    result = cli.fix_loop(
        client=client,
        reviewer=reviewer,
        user=client.current_user(),
        max_fixes=None,
        once=True,
        dry_run=True,
        stdout=stdout,
    )

    assert result == 0
    assert reviewer.prompts == []
    assert "Fix this Wardn Hub draft or rejected submission" in stdout.getvalue()
    assert client.submissions[0]["status"] == "rejected"


def test_parser_uses_expected_defaults() -> None:
    args = cli.build_parser().parse_args(["--submission-id", "sub-1", "--dry-run"])

    assert args.submission_id == "sub-1"
    assert args.dry_run is True
    assert args.review_command == cli.DEFAULT_REVIEW_COMMAND
