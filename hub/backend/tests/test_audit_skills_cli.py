import base64
import json
import uuid
from io import StringIO

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app import manage
from app.cli import audit_skills as cli
from app.cli.review_pending_submissions import UserFacingError


def valid_skill_md(*, body: str = "# Weather\n\nUse the weather API carefully.") -> str:
    return (
        "---\n"
        "name: weather\n"
        "description: Provides a careful weather workflow.\n"
        "---\n\n"
        f"{body}\n"
    )


def audit_target(*, files: list[dict] | None = None) -> cli.SkillAuditTarget:
    skill_md = valid_skill_md()
    bundle_files = files or [{"path": "SKILL.md", "contents": skill_md}]
    return cli.SkillAuditTarget(
        skill_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        snapshot_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        content_hash=cli.bundle_content_hash(bundle_files),
        source="acme/skills",
        slug="weather",
        name="Weather",
        description="Provides a careful weather workflow.",
        source_url="https://github.com/acme/skills",
        skill_md=skill_md,
        files=bundle_files,
    )


def codex_output(
    *,
    status: str = "pass",
    risk_level: str = "low",
    findings: list[dict] | None = None,
) -> str:
    payload = {
        "status": status,
        "riskLevel": risk_level,
        "summary": "No material safety issue found.",
        "categories": ["instruction-safety"],
        "findings": findings or [],
    }
    return "Skill audit result JSON\n```json\n" + json.dumps(payload) + "\n```"


class FakeReviewer:
    def __init__(self, output: str | None = None) -> None:
        self.output = output or codex_output()
        self.prompts: list[str] = []
        self.environments: list[dict[str, str]] = []

    def review(self, prompt: str, *, environment: dict[str, str]) -> str:
        self.prompts.append(prompt)
        self.environments.append(environment)
        return self.output


class FakeClient:
    def __init__(self, targets: list[cli.SkillAuditTarget]) -> None:
        self.targets = list(targets)
        self.next_calls: list[uuid.UUID | None] = []
        self.saved: list[tuple[cli.SkillAuditTarget, list[cli.StoredAudit], bool]] = []

    def next_target(
        self,
        *,
        after_skill_id: uuid.UUID | None,
        skill_id: str | None,
        re_audit: bool,
    ) -> cli.SkillAuditTarget | None:
        self.next_calls.append(after_skill_id)
        if not self.targets:
            return None
        return self.targets.pop(0)

    def save_audits(
        self,
        target: cli.SkillAuditTarget,
        audits: list[cli.StoredAudit],
        *,
        re_audit: bool,
    ) -> str:
        self.saved.append((target, audits, re_audit))
        return "saved"


def test_completed_audit_condition_for_snapshot_only_queries_audits() -> None:
    target = audit_target()
    statement = select(
        cli.completed_audit_condition(
            skill_id=target.skill_id,
            snapshot_id=target.snapshot_id,
            content_hash=target.content_hash,
        )
    )

    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "FROM skill_audits" in sql
    assert "FROM skills" not in sql
    assert "FROM skill_snapshots" not in sql


def test_inspect_bundle_accepts_resolver_compatible_bundle() -> None:
    target = audit_target(
        files=[
            {"path": "SKILL.md", "contents": valid_skill_md()},
            {
                "path": "scripts/check.sh",
                "contents": "#!/bin/sh\nset -eu\nprintf '%s\\n' safe\n",
                "executable": True,
            },
            {
                "path": "assets/icon.png",
                "contents": base64.b64encode(b"png-data").decode(),
                "encoding": "base64",
            },
        ]
    )

    inspection = cli.inspect_bundle(target)

    assert inspection.hard_findings == []
    assert inspection.total_bytes > 0
    assert [item["path"] for item in inspection.decoded_files] == [
        "SKILL.md",
        "scripts/check.sh",
        "assets/icon.png",
    ]


def test_inspect_bundle_rejects_opaque_executable() -> None:
    target = audit_target(
        files=[
            {"path": "SKILL.md", "contents": valid_skill_md()},
            {
                "path": "bin/helper",
                "contents": base64.b64encode(b"opaque").decode(),
                "encoding": "base64",
                "executable": True,
            },
        ]
    )

    decision = cli.policy_decision(cli.inspect_bundle(target))

    assert decision.status == "fail"
    assert decision.risk_level == "high"
    assert "opaque-executable" in decision.categories


def test_inspect_bundle_rejects_snapshot_root_mismatch() -> None:
    target = audit_target(
        files=[{"path": "SKILL.md", "contents": valid_skill_md(body="# Changed")}]
    )

    decision = cli.policy_decision(cli.inspect_bundle(target))

    assert decision.status == "fail"
    assert "invalid-bundle" in decision.categories


def test_resolver_frontmatter_validation_matches_supported_scalar_rules() -> None:
    assert cli.resolver_frontmatter_valid(
        "---\nname: 'weather'\ndescription: |\n  Safe workflow.\n---\n# Weather\n"
    )
    assert not cli.resolver_frontmatter_valid(
        "---\nname: 123\ndescription: Safe workflow.\n---\n# Weather\n"
    )
    assert not cli.resolver_frontmatter_valid(
        "---\nname: weather\nname: duplicate\ndescription: Safe workflow.\n---\n# Weather\n"
    )


def test_build_audit_prompt_omits_text_that_exceeds_prompt_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = audit_target(
        files=[
            {"path": "SKILL.md", "contents": valid_skill_md()},
            {"path": "references/large.txt", "contents": "x" * 20_000},
        ]
    )
    inspection = cli.inspect_bundle(target)
    monkeypatch.setattr(cli, "MAX_AUDIT_PROMPT_CHARS", 15_000)

    prompt = cli.build_audit_prompt(target, inspection)
    decision = cli.policy_decision(inspection, omitted_paths=prompt.omitted_paths)

    assert prompt.omitted_paths == ["references/large.txt"]
    assert len(prompt.text) <= 15_000
    assert decision.status == "warn"
    assert "partial-content-review" in decision.categories


def test_extract_skill_audit_result_requires_label_and_valid_risk() -> None:
    assert cli.extract_skill_audit_result(codex_output()) is not None
    assert cli.extract_skill_audit_result('{"status":"pass"}') is None
    assert (
        cli.extract_skill_audit_result(
            codex_output(status="pass", risk_level="critical")
        )
        is None
    )


def test_review_with_retries_waits_indefinitely_for_rate_limit() -> None:
    attempts = 0
    sleeps: list[float] = []

    class RateLimitedReviewer:
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise UserFacingError("HTTP 429 rate limit; retry-after: 7")
            return codex_output()

    output, decision = cli.review_with_retries(
        RateLimitedReviewer(),
        "prompt",
        environment={},
        max_attempts=1,
        rate_limit_base_seconds=60,
        rate_limit_max_seconds=900,
        stdout=StringIO(),
        sleep=sleeps.append,
    )

    assert output == codex_output()
    assert decision.status == "pass"
    assert attempts == 3
    assert sleeps == [7.0, 7.0]


def test_audit_skills_streams_and_stores_snapshot_bound_results() -> None:
    target = audit_target()
    client = FakeClient([target])
    reviewer = FakeReviewer()
    stdout = StringIO()

    result = cli.audit_skills(
        client=client,
        reviewer=reviewer,
        max_skills=None,
        skill_id=None,
        re_audit=False,
        dry_run=False,
        max_attempts=3,
        rate_limit_base_seconds=60,
        rate_limit_max_seconds=900,
        stdout=stdout,
        sleep=lambda _delay: None,
    )

    assert result == 0
    assert len(client.saved) == 1
    assert [audit.slug for audit in client.saved[0][1]] == [
        cli.POLICY_PROVIDER_SLUG,
        cli.CODEX_PROVIDER_SLUG,
    ]
    assert client.saved[0][1][1].raw_result["contentHash"] == target.content_hash
    assert reviewer.environments[0]["WARDN_HUB_SKILL_AUDIT_ID"] == target.catalog_id
    assert client.next_calls == [None, target.skill_id]
    assert "pass=1" in stdout.getvalue()


def test_audit_skills_stores_deterministic_failure_without_codex() -> None:
    target = audit_target(
        files=[
            {"path": "SKILL.md", "contents": valid_skill_md()},
            {
                "path": "bin/helper",
                "contents": base64.b64encode(b"opaque").decode(),
                "encoding": "base64",
                "executable": True,
            },
        ]
    )
    client = FakeClient([target])
    reviewer = FakeReviewer()

    result = cli.audit_skills(
        client=client,
        reviewer=reviewer,
        max_skills=None,
        skill_id=None,
        re_audit=False,
        dry_run=False,
        max_attempts=3,
        rate_limit_base_seconds=60,
        rate_limit_max_seconds=900,
        stdout=StringIO(),
        sleep=lambda _delay: None,
    )

    assert result == 0
    assert reviewer.prompts == []
    assert len(client.saved[0][1]) == 1
    assert client.saved[0][1][0].decision.status == "fail"


def test_audit_skills_leaves_codex_errors_resumable() -> None:
    class FailingReviewer:
        def review(self, prompt: str, *, environment: dict[str, str]) -> str:
            raise UserFacingError("review unavailable")

    client = FakeClient([audit_target()])

    result = cli.audit_skills(
        client=client,
        reviewer=FailingReviewer(),
        max_skills=None,
        skill_id=None,
        re_audit=False,
        dry_run=False,
        max_attempts=2,
        rate_limit_base_seconds=60,
        rate_limit_max_seconds=900,
        stdout=StringIO(),
        sleep=lambda _delay: None,
    )

    assert result == 1
    assert client.saved == []


def test_manage_dispatches_skills_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = []

    def fake_audit(args) -> int:
        captured.append(args)
        return 0

    monkeypatch.setattr(manage, "audit_skills_from_args", fake_audit)

    assert manage.main(["skills", "audit", "--dry-run", "--max-skills", "2"]) == 0
    assert captured[0].dry_run is True
    assert captured[0].max_skills == 2
