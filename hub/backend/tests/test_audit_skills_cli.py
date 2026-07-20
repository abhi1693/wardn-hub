import base64
import json
import subprocess
import uuid
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app import manage
from app.cli import audit_skills as cli
from app.modules.skills import audit_policy
from app.modules.skills.audit_policy import audit_configuration_hash


def valid_skill_md(*, body: str = "# Weather\n\nUse the weather API carefully.") -> str:
    return f"---\nname: weather\ndescription: Provides a careful weather workflow.\n---\n\n{body}\n"


def audit_target(
    *,
    files: list[dict] | None = None,
    skill_md: str | None = None,
) -> cli.SkillAuditTarget:
    skill_md = skill_md or valid_skill_md()
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


def scan_payload(
    *,
    findings: list[dict] | None = None,
    failed: list[dict] | None = None,
    analyzers: list[str] | None = None,
):
    findings = findings or []
    severity_order = ["critical", "high", "medium", "low", "info"]
    maximum = next(
        (level for level in severity_order if any(item["severity"] == level for item in findings)),
        "safe",
    )
    return cli.CiscoScanPayload.model_validate(
        {
            "skill_name": "weather",
            "is_safe": maximum not in {"critical", "high"},
            "max_severity": maximum,
            "findings_count": len(findings),
            "findings": findings,
            "duration_ms": 123,
            "analyzers_used": analyzers
            if analyzers is not None
            else [
                "static_analyzer",
                "bytecode",
                "pipeline",
                "behavioral_analyzer",
            ],
            "analyzers_failed": failed or [],
            "scan_metadata": {
                "policy_name": "balanced",
                "policy_version": "1.0",
                "policy_fingerprint_sha256": "a" * 64,
            },
        }
    )


def scanner_finding(
    severity: str,
    *,
    category: str = "prompt-injection",
    identifier: str = "RULE-1",
) -> dict:
    return {
        "id": identifier,
        "rule_id": identifier,
        "category": category,
        "severity": severity,
        "title": "Unsafe instruction",
        "description": "The skill contains a risky instruction.",
        "file_path": "SKILL.md",
        "line_number": 8,
        "remediation": "Remove the instruction.",
        "analyzer": "static_analyzer",
    }


class FakeClient:
    def __init__(self, targets: list[cli.SkillAuditTarget]) -> None:
        self.targets = list(targets)
        self.next_calls: list[uuid.UUID | None] = []
        self.saved: list[tuple[cli.SkillAuditTarget, cli.StoredAudit, bool]] = []

    def next_target(self, *, after_skill_id, skill_id, re_audit):
        self.next_calls.append(after_skill_id)
        return self.targets.pop(0) if self.targets else None

    def save_audit(self, target, audit, *, re_audit):
        self.saved.append((target, audit, re_audit))
        return "saved"


class FakeScanner:
    def __init__(self, payload: cli.CiscoScanPayload | None = None) -> None:
        self.payload = payload or scan_payload()
        self.calls: list[cli.SkillAuditTarget] = []
        self.configuration_hash = audit_configuration_hash(llm_enabled=False)

    def scan(self, target, inspection):
        self.calls.append(target)
        return cli.stored_scanner_audit(
            target,
            self.payload,
            llm_enabled=False,
            configuration_hash=self.configuration_hash,
        )


def test_completed_audit_condition_is_snapshot_bound_across_configurations() -> None:
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
    assert "configuration_hash" not in sql
    assert str(target.snapshot_id) in sql
    assert target.content_hash in sql


def test_llm_gate_changes_audit_configuration_hash() -> None:
    assert audit_configuration_hash(llm_enabled=False) != audit_configuration_hash(llm_enabled=True)


def test_llm_routing_changes_audit_configuration_hash_only_when_enabled() -> None:
    assert audit_configuration_hash(
        llm_enabled=True,
        llm_provider="openai",
        llm_model="model-a",
    ) != audit_configuration_hash(
        llm_enabled=True,
        llm_provider="openai",
        llm_model="model-b",
    )
    assert audit_configuration_hash(
        llm_enabled=False,
        llm_model="model-a",
    ) == audit_configuration_hash(
        llm_enabled=False,
        llm_model="model-b",
    )


def test_current_audit_hash_reads_non_secret_llm_routing(monkeypatch) -> None:
    monkeypatch.setattr(
        audit_policy,
        "get_settings",
        lambda: SimpleNamespace(skill_audit_llm_enabled=True),
    )
    monkeypatch.setenv("SKILL_SCANNER_LLM_PROVIDER", "openai")
    monkeypatch.setenv("SKILL_SCANNER_LLM_MODEL", "test-model")
    monkeypatch.setenv("SKILL_SCANNER_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("SKILL_SCANNER_LLM_API_VERSION", "2026-01-01")
    monkeypatch.setenv("SKILL_SCANNER_LLM_TEMPERATURE", "0")

    assert audit_policy.current_audit_configuration_hash() == audit_configuration_hash(
        llm_enabled=True,
        llm_provider="openai",
        llm_model="test-model",
        llm_base_url="https://llm.example.test/v1",
        llm_api_version="2026-01-01",
        llm_temperature="0",
    )


def test_inspect_bundle_accepts_safe_materializable_bundle() -> None:
    skill_md = valid_skill_md(body="# Weather\n\nRead [the guide](references/guide.md).")
    target = audit_target(
        skill_md=skill_md,
        files=[
            {"path": "SKILL.md", "contents": skill_md},
            {"path": "references/guide.md", "contents": "# Guide\n"},
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
        ],
    )
    inspection = cli.inspect_bundle(target)
    assert inspection.hard_findings == []
    assert inspection.total_bytes > 0
    assert set(inspection.materialized_files) == {
        "SKILL.md",
        "references/guide.md",
        "scripts/check.sh",
        "assets/icon.png",
    }


def test_security_preflight_does_not_grade_dependency_compatibility() -> None:
    skill_md = valid_skill_md(body="# Weather\n\nRead ../missing-required.md.")
    target = audit_target(
        skill_md=skill_md,
        files=[{"path": "SKILL.md", "contents": skill_md}],
    )

    assert cli.inspect_bundle(target).hard_findings == []


@pytest.mark.parametrize(
    "files",
    [
        [
            {"path": "SKILL.md", "contents": valid_skill_md()},
            {
                "path": "bin/helper",
                "contents": base64.b64encode(b"opaque").decode(),
                "encoding": "base64",
                "executable": True,
            },
        ],
        [{"path": "SKILL.md", "contents": valid_skill_md(body="Read ../secret.md")}],
    ],
)
def test_invalid_bundles_fail_before_scanner(files: list[dict]) -> None:
    target = audit_target(files=files)
    inspection = cli.inspect_bundle(target)
    scanner = FakeScanner()
    client = FakeClient([target])
    result = cli.audit_skills(
        client=client,
        scanner=scanner,
        max_skills=None,
        skill_id=None,
        re_audit=False,
        dry_run=False,
        stdout=StringIO(),
    )
    assert inspection.hard_findings
    assert result == 1
    assert scanner.calls == []
    assert client.saved == []


@pytest.mark.parametrize(
    ("findings", "score", "rank"),
    [
        ([], 100, "S"),
        ([scanner_finding("info")], 99, "S"),
        ([scanner_finding("low")], 96, "A+"),
        ([scanner_finding("medium")], 79, "A"),
        ([scanner_finding("high")], 49, "B"),
        ([scanner_finding("critical")], 24, "C+"),
    ],
)
def test_security_score_has_github_style_ranks_and_severity_floors(
    findings: list[dict], score: int, rank: str
) -> None:
    audit = cli.stored_scanner_audit(
        audit_target(),
        scan_payload(findings=findings),
        llm_enabled=False,
        configuration_hash=audit_configuration_hash(llm_enabled=False),
    )
    assert audit.score == score
    assert audit.rank == rank


def test_every_category_and_repeated_finding_deducts_score() -> None:
    findings = [
        scanner_finding("low", category="network", identifier="NETWORK-1"),
        scanner_finding("low", category="network", identifier="NETWORK-2"),
        scanner_finding("low", category="filesystem", identifier="FILESYSTEM-1"),
    ]
    score, _rank, deductions = cli.score_findings(
        [cli.normalized_finding(cli.CiscoFinding.model_validate(item)) for item in findings]
    )
    assert score == 91
    assert {item["category"] for item in deductions} == {"network", "filesystem"}
    assert next(item for item in deductions if item["category"] == "network")["points"] == 5


def test_analyzer_failure_forces_warning_and_incomplete_analysis_deduction() -> None:
    audit = cli.stored_scanner_audit(
        audit_target(),
        scan_payload(failed=[{"analyzer": "pipeline_analyzer", "error": "failed"}]),
        llm_enabled=False,
        configuration_hash=audit_configuration_hash(llm_enabled=False),
    )
    assert audit.status == "warn"
    assert audit.score == 79
    assert "coverage is incomplete" in audit.summary
    assert audit.policy_fingerprint == "a" * 64


@pytest.mark.parametrize(
    ("analyzers", "failed"),
    [
        ([*sorted(cli.REQUIRED_LOCAL_ANALYZERS)], []),
        (
            [*sorted(cli.REQUIRED_LOCAL_ANALYZERS), cli.LLM_ANALYZER],
            [{"analyzer": cli.LLM_ANALYZER, "error": "failed"}],
        ),
    ],
)
def test_llm_gate_requires_analyzer_completion(
    analyzers: list[str],
    failed: list[dict],
) -> None:
    with pytest.raises(cli.UserFacingError, match="did not complete"):
        cli.stored_scanner_audit(
            audit_target(),
            scan_payload(analyzers=analyzers, failed=failed),
            llm_enabled=True,
            configuration_hash=audit_configuration_hash(llm_enabled=True),
        )


def test_cisco_uppercase_severities_are_normalized() -> None:
    payload = scan_payload(findings=[scanner_finding("high")]).model_dump(mode="json")
    payload["max_severity"] = "HIGH"
    payload["findings"][0]["severity"] = "HIGH"

    parsed = cli.CiscoScanPayload.model_validate(payload)

    assert parsed.max_severity == "high"
    assert parsed.findings[0].severity == "high"


def test_audit_stream_stores_one_snapshot_result() -> None:
    target = audit_target()
    client = FakeClient([target])
    scanner = FakeScanner()
    stdout = StringIO()
    result = cli.audit_skills(
        client=client,
        scanner=scanner,
        max_skills=None,
        skill_id=None,
        re_audit=False,
        dry_run=False,
        stdout=stdout,
    )
    assert result == 0
    assert scanner.calls == [target]
    assert len(client.saved) == 1
    assert client.saved[0][1].scanner_name == cli.SCANNER_NAME
    assert client.saved[0][1].score == 100
    assert client.next_calls == [None, target.skill_id]
    assert "pass=1" in stdout.getvalue()


def test_audit_scanner_errors_remain_resumable() -> None:
    class FailingScanner:
        def scan(self, target, inspection):
            raise cli.UserFacingError("scanner unavailable")

    client = FakeClient([audit_target()])
    result = cli.audit_skills(
        client=client,
        scanner=FailingScanner(),
        max_skills=None,
        skill_id=None,
        re_audit=False,
        dry_run=False,
        stdout=StringIO(),
    )
    assert result == 1
    assert client.saved == []


def test_cisco_scanner_invocation_enables_only_local_analyzers(monkeypatch) -> None:
    target = audit_target()
    inspection = cli.inspect_bundle(target)
    captured: list[str] = []
    payload = scan_payload().model_dump(mode="json")

    def fake_run(command, **kwargs):
        captured.extend(command)
        report_path = Path(command[command.index("--output-json") + 1])
        report_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=b"scanner progress that is not JSON\n",
            stderr=b"",
        )

    monkeypatch.setattr(cli, "version", lambda _name: cli.SCANNER_VERSION)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    audit = cli.CiscoSkillScanner(
        timeout_seconds=12,
        llm_enabled=False,
        configuration_hash=audit_configuration_hash(llm_enabled=False),
    ).scan(target, inspection)

    assert audit.status == "pass"
    assert "--use-behavioral" in captured
    assert "--policy" in captured
    assert "--use-llm" not in captured
    assert "--enable-meta" not in captured
    assert "--use-aidefense" not in captured
    assert "--use-virustotal" not in captured


def test_cisco_scanner_invocation_enables_llm_when_gated_on(monkeypatch) -> None:
    target = audit_target()
    inspection = cli.inspect_bundle(target)
    captured: list[str] = []
    payload = scan_payload(
        analyzers=[*sorted(cli.REQUIRED_LOCAL_ANALYZERS), cli.LLM_ANALYZER]
    ).model_dump(mode="json")

    def fake_run(command, **kwargs):
        captured.extend(command)
        report_path = Path(command[command.index("--output-json") + 1])
        report_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=b"scanner progress that is not JSON\n",
            stderr=b"",
        )

    monkeypatch.setattr(cli, "version", lambda _name: cli.SCANNER_VERSION)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    audit = cli.CiscoSkillScanner(
        timeout_seconds=12,
        llm_enabled=True,
        configuration_hash=audit_configuration_hash(
            llm_enabled=True,
            llm_provider="openai",
            llm_model="test-model",
        ),
    ).scan(target, inspection)

    assert audit.status == "pass"
    assert "--use-llm" in captured
    assert "--use-aidefense" not in captured
    assert audit.configuration_hash == audit_configuration_hash(
        llm_enabled=True,
        llm_provider="openai",
        llm_model="test-model",
    )


def test_cisco_scanner_smoke_runs_pinned_distribution() -> None:
    target = audit_target()
    audit = cli.CiscoSkillScanner(
        timeout_seconds=30,
        llm_enabled=False,
        configuration_hash=audit_configuration_hash(llm_enabled=False),
    ).scan(
        target,
        cli.inspect_bundle(target),
    )

    assert audit.scanner_name == cli.SCANNER_NAME
    assert audit.scanner_version == cli.SCANNER_VERSION
    assert audit.configuration_hash == audit_configuration_hash(llm_enabled=False)
    assert cli.REQUIRED_LOCAL_ANALYZERS.issubset(audit.analyzers)
    assert audit.raw_result["scanCompleted"] is True
    assert 0 <= audit.score <= 100


def test_audit_command_is_blocked_when_feature_gate_is_disabled(monkeypatch) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(skill_audit_enabled=False))
    args = cli.build_parser().parse_args(["--dry-run", "--max-skills", "1"])
    with pytest.raises(cli.UserFacingError, match="WARDN_HUB_SKILL_AUDIT_ENABLED"):
        cli.audit_skills_from_args(args)


def test_manage_dispatches_skills_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = []

    def fake_audit(args) -> int:
        captured.append(args)
        return 0

    monkeypatch.setattr(manage, "audit_skills_from_args", fake_audit)
    assert manage.main(["skills", "audit", "--dry-run", "--max-skills", "2"]) == 0
    assert captured[0].dry_run is True
    assert captured[0].max_skills == 2
