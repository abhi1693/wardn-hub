from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import hashlib
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol, TextIO

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import and_, exists, select
from sqlalchemy.exc import DBAPIError

from app.cli.skills import content_hash as bundle_content_hash
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.modules.skills.audit_policy import (
    SCANNER_BEHAVIORAL_ENABLED,
    SCANNER_DISTRIBUTION,
    SCANNER_NAME,
    SCANNER_POLICY,
    SCANNER_VERSION,
    current_audit_configuration_hash,
)
from app.modules.skills.models import Skill, SkillAudit, SkillSnapshot
from app.modules.skills.service import split_skill_id

MAX_SKILL_FILES = 256
MAX_SKILL_FILE_BYTES = 8 * 1024 * 1024
MAX_SKILL_BUNDLE_BYTES = 16 * 1024 * 1024
MAX_ROOT_SKILL_CHARS = 65_536
MAX_PATH_CHARS = 1_024
MAX_PATH_PARTS = 64
MAX_SCANNER_OUTPUT_BYTES = 10 * 1024 * 1024
MAX_STORED_FINDINGS = 500
DEFAULT_SCANNER_TIMEOUT_SECONDS = 300
REQUIRED_LOCAL_ANALYZERS = {
    "static_analyzer",
    "bytecode",
    "pipeline",
    "behavioral_analyzer",
}
LLM_ANALYZER = "llm_analyzer"
SEVERITY_DEDUCTIONS = {"safe": 0, "info": 1, "low": 4, "medium": 12, "high": 35, "critical": 60}
SEVERITY_SCORE_CAPS = {"medium": 79, "high": 49, "critical": 24}
WINDOWS_RESERVED_PATH_PATTERN = re.compile(
    r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.IGNORECASE
)


class UserFacingError(Exception):
    pass


class CiscoFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default="", max_length=256)
    rule_id: str = Field(default="", max_length=256)
    category: str = Field(default="unknown", max_length=256)
    severity: Literal["safe", "info", "low", "medium", "high", "critical"]
    title: str = Field(default="Security finding", max_length=2_000)
    description: str = Field(default="", max_length=10_000)
    file_path: str | None = Field(default=None, max_length=2_048)
    line_number: int | None = Field(default=None, ge=1)
    snippet: str | None = Field(default=None, max_length=10_000)
    remediation: str | None = Field(default=None, max_length=10_000)
    analyzer: str = Field(default="unknown", max_length=256)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value


class CiscoScanPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    skill_name: str = ""
    is_safe: bool
    max_severity: Literal["safe", "info", "low", "medium", "high", "critical"]
    findings_count: int = Field(ge=0)
    findings: list[CiscoFinding] = Field(default_factory=list, max_length=2_000)
    duration_ms: int = Field(default=0, ge=0)
    analyzers_used: list[str] = Field(default_factory=list, max_length=128)
    analyzers_failed: list[dict[str, Any]] = Field(default_factory=list, max_length=128)
    scan_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("max_severity", mode="before")
    @classmethod
    def normalize_max_severity(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("analyzers_used")
    @classmethod
    def validate_analyzer_names(cls, value: list[str]) -> list[str]:
        if any(not item or len(item) > 128 for item in value):
            raise ValueError("analyzer names must contain between 1 and 128 characters")
        return value


@dataclass(frozen=True)
class SkillAuditTarget:
    skill_id: uuid.UUID
    snapshot_id: uuid.UUID
    content_hash: str
    source: str
    slug: str
    name: str
    description: str
    source_url: str
    skill_md: str
    files: list[dict[str, Any]]

    @property
    def catalog_id(self) -> str:
        return f"{self.source}/{self.slug}"


@dataclass
class BundleInspection:
    hard_findings: list[dict[str, Any]] = field(default_factory=list)
    decoded_files: list[dict[str, Any]] = field(default_factory=list)
    materialized_files: dict[str, bytes] = field(default_factory=dict)
    total_bytes: int = 0


@dataclass(frozen=True)
class StoredAudit:
    scanner_name: str
    scanner_version: str
    policy_name: str
    policy_version: str
    policy_fingerprint: str
    configuration_hash: str
    status: Literal["pass", "warn", "fail"]
    summary: str
    risk_level: Literal["low", "medium", "high", "critical"]
    score: int
    rank: str
    score_deductions: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    analyzers: list[str]
    scan_duration_ms: int
    raw_result: dict[str, Any]


@dataclass
class AuditStats:
    seen: int = 0
    passed: int = 0
    warned: int = 0
    failed: int = 0
    errors: int = 0
    stale: int = 0


class SkillAuditDatabaseClient(Protocol):
    def next_target(
        self,
        *,
        after_skill_id: uuid.UUID | None,
        skill_id: str | None,
        re_audit: bool,
    ) -> SkillAuditTarget | None: ...

    def save_audit(
        self,
        target: SkillAuditTarget,
        audit: StoredAudit,
        *,
        re_audit: bool,
    ) -> Literal["saved", "stale", "already-audited"]: ...


class SkillScanner(Protocol):
    configuration_hash: str

    def scan(self, target: SkillAuditTarget, inspection: BundleInspection) -> StoredAudit: ...


def completed_audit_condition(
    *,
    skill_id: Any = Skill.id,
    snapshot_id: Any = SkillSnapshot.id,
    content_hash: Any = SkillSnapshot.content_hash,
) -> Any:
    # The configuration hash is provenance, not audit validity. An unchanged
    # snapshot remains audited when its LLM provider or model is replaced.
    return exists(
        select(SkillAudit.id)
        .where(
            SkillAudit.skill_id == skill_id,
            SkillAudit.snapshot_id == snapshot_id,
            SkillAudit.content_hash == content_hash,
            SkillAudit.status.in_(("pass", "warn", "fail")),
        )
        .correlate(Skill, SkillSnapshot)
    )


def is_transient_database_disconnect(exc: BaseException) -> bool:
    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return True
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "connection is closed",
            "connection was closed",
            "connection reset",
            "connection terminated",
            "server closed the connection",
        )
    )


class WardnHubDatabaseSkillAuditClient:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()

    def close(self) -> None:
        if not self._loop.is_closed():
            self._loop.close()

    def _run(self, operation: Any, *, commit: bool = False) -> Any:
        async def run() -> Any:
            async with AsyncSessionLocal() as session:
                try:
                    result = await operation(session)
                    if commit:
                        await session.commit()
                    return result
                except Exception:
                    await session.rollback()
                    raise

        for attempt in range(2):
            try:
                return self._loop.run_until_complete(run())
            except Exception as exc:
                if commit or attempt == 1 or not is_transient_database_disconnect(exc):
                    raise
                time.sleep(1)
        raise RuntimeError("unreachable database retry state")

    def next_target(
        self,
        *,
        after_skill_id: uuid.UUID | None,
        skill_id: str | None,
        re_audit: bool,
    ) -> SkillAuditTarget | None:
        async def operation(session: Any) -> SkillAuditTarget | None:
            statement = (
                select(Skill, SkillSnapshot)
                .join(
                    SkillSnapshot,
                    and_(
                        SkillSnapshot.id == Skill.current_snapshot_id,
                        SkillSnapshot.skill_id == Skill.id,
                    ),
                )
                .where(
                    Skill.status == "active",
                    Skill.visibility == "public",
                    Skill.current_snapshot_id.is_not(None),
                    SkillSnapshot.status == "active",
                    SkillSnapshot.is_latest.is_(True),
                    SkillSnapshot.content_hash.is_not(None),
                    SkillSnapshot.bundle_format_version == 2,
                    SkillSnapshot.resolution_status == "complete",
                )
            )
            if after_skill_id is not None:
                statement = statement.where(Skill.id > after_skill_id)
            if skill_id:
                source, slug = split_skill_id(skill_id)
                statement = statement.where(Skill.source == source, Skill.slug == slug)
            if not re_audit:
                statement = statement.where(~completed_audit_condition())
            row = (await session.execute(statement.order_by(Skill.id.asc()).limit(1))).first()
            if row is None:
                return None
            skill, snapshot = row
            return SkillAuditTarget(
                skill_id=skill.id,
                snapshot_id=snapshot.id,
                content_hash=str(snapshot.content_hash),
                source=skill.source,
                slug=skill.slug,
                name=skill.name,
                description=skill.description,
                source_url=skill.source_url,
                skill_md=snapshot.skill_md,
                files=[dict(item) for item in (snapshot.files or [])],
            )

        return self._run(operation)

    def save_audit(
        self,
        target: SkillAuditTarget,
        audit: StoredAudit,
        *,
        re_audit: bool,
    ) -> Literal["saved", "stale", "already-audited"]:
        async def operation(session: Any) -> str:
            skill = (
                await session.execute(
                    select(Skill).where(Skill.id == target.skill_id).with_for_update()
                )
            ).scalar_one_or_none()
            if skill is None or skill.current_snapshot_id != target.snapshot_id:
                return "stale"
            snapshot = (
                await session.execute(
                    select(SkillSnapshot).where(
                        SkillSnapshot.id == target.snapshot_id,
                        SkillSnapshot.skill_id == target.skill_id,
                        SkillSnapshot.status == "active",
                        SkillSnapshot.is_latest.is_(True),
                        SkillSnapshot.bundle_format_version == 2,
                        SkillSnapshot.resolution_status == "complete",
                    )
                )
            ).scalar_one_or_none()
            if snapshot is None or snapshot.content_hash != target.content_hash:
                return "stale"

            stored = (
                await session.execute(
                    select(SkillAudit)
                    .where(SkillAudit.snapshot_id == target.snapshot_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if stored is not None and not re_audit:
                return "already-audited"
            values = {
                "skill_id": target.skill_id,
                "snapshot_id": target.snapshot_id,
                "content_hash": target.content_hash,
                "scanner_name": audit.scanner_name,
                "scanner_version": audit.scanner_version,
                "policy_name": audit.policy_name,
                "policy_version": audit.policy_version,
                "policy_fingerprint": audit.policy_fingerprint,
                "configuration_hash": audit.configuration_hash,
                "status": audit.status,
                "summary": audit.summary,
                "risk_level": audit.risk_level,
                "score": audit.score,
                "rank": audit.rank,
                "score_deductions": audit.score_deductions,
                "findings": audit.findings,
                "analyzers": audit.analyzers,
                "scan_duration_ms": audit.scan_duration_ms,
                "raw_result": audit.raw_result,
                "audited_at": datetime.now(UTC),
            }
            if stored is None:
                session.add(SkillAudit(**values))
            else:
                for key, value in values.items():
                    setattr(stored, key, value)
            return "saved"

        return self._run(operation, commit=True)


def safe_text(value: str) -> bool:
    for char in value:
        codepoint = ord(char)
        if codepoint in {9, 10, 13}:
            continue
        if codepoint < 32 or 127 <= codepoint <= 159:
            return False
        if codepoint == 1564 or 8206 <= codepoint <= 8207:
            return False
        if 8234 <= codepoint <= 8238 or 8294 <= codepoint <= 8297:
            return False
    return True


def safe_bundle_path(path: str) -> bool:
    if not path or len(path) > MAX_PATH_CHARS or path.startswith("/") or "\\" in path:
        return False
    if not safe_text(path):
        return False
    parts = path.split("/")
    return (
        len(parts) <= MAX_PATH_PARTS
        and all(
            part not in {"", ".", ".."}
            and ":" not in part
            and not part.endswith((".", " "))
            and len(part.encode("utf-8")) <= 255
            and not WINDOWS_RESERVED_PATH_PATTERN.match(part)
            for part in parts
        )
        and PurePosixPath(path).as_posix() == path
    )


def resolver_frontmatter_valid(contents: str) -> bool:
    lines = contents.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration:
        return False
    if not any(line.strip() for line in lines[closing_index + 1 :]):
        return False
    try:
        metadata = yaml.safe_load("\n".join(lines[1:closing_index]))
    except yaml.YAMLError:
        return False
    return bool(
        isinstance(metadata, dict)
        and isinstance(metadata.get("name"), str)
        and metadata["name"].strip()
        and isinstance(metadata.get("description"), str)
        and metadata["description"].strip()
    )


def validation_finding(category: str, description: str, path: str | None = None) -> dict[str, Any]:
    return {
        "id": f"WARDN-{category.upper()}",
        "ruleId": f"WARDN_{category.upper().replace('-', '_')}",
        "category": category,
        "severity": "high",
        "title": "Skill bundle failed pre-scan validation",
        "description": description[:10_000],
        "filePath": path,
        "lineNumber": None,
        "snippet": None,
        "remediation": "Publish a resolver-compatible, self-contained skill bundle.",
        "analyzer": "wardn_bundle_preflight",
        "metadata": {},
    }


def inspect_bundle(target: SkillAuditTarget) -> BundleInspection:
    inspection = BundleInspection()
    if len(target.files) > MAX_SKILL_FILES:
        inspection.hard_findings.append(
            validation_finding("invalid-bundle", "Bundle exceeds the 256 file limit.")
        )
    seen_paths: set[str] = set()
    for item in target.files[: MAX_SKILL_FILES + 1]:
        path = item.get("path")
        contents = item.get("contents")
        encoding = item.get("encoding", "utf-8")
        executable = item.get("executable", False)
        if not isinstance(path, str) or not safe_bundle_path(path) or path in seen_paths:
            inspection.hard_findings.append(
                validation_finding("invalid-bundle", "Bundle has an unsafe or duplicate path.")
            )
            continue
        seen_paths.add(path)
        if not isinstance(contents, str) or encoding not in {"utf-8", "base64"}:
            inspection.hard_findings.append(
                validation_finding("invalid-bundle", "File content or encoding is invalid.", path)
            )
            continue
        if not isinstance(executable, bool):
            inspection.hard_findings.append(
                validation_finding("invalid-bundle", "Executable metadata must be boolean.", path)
            )
            continue
        try:
            decoded = (
                contents.encode("utf-8")
                if encoding == "utf-8"
                else base64.b64decode(contents, validate=True)
            )
        except (UnicodeEncodeError, binascii.Error, ValueError):
            inspection.hard_findings.append(
                validation_finding("invalid-bundle", "File content cannot be decoded.", path)
            )
            continue
        if len(decoded) > MAX_SKILL_FILE_BYTES:
            inspection.hard_findings.append(
                validation_finding("invalid-bundle", "File exceeds the 8 MiB limit.", path)
            )
        if executable and encoding != "utf-8":
            inspection.hard_findings.append(
                validation_finding(
                    "opaque-executable",
                    "Executable files must be inspectable UTF-8 source text.",
                    path,
                )
            )
        inspection.total_bytes += len(decoded)
        inspection.materialized_files[path] = decoded
        summary: dict[str, Any] = {
            "path": path,
            "encoding": encoding,
            "executable": executable,
            "decodedBytes": len(decoded),
            "sha256": hashlib.sha256(decoded).hexdigest(),
        }
        if encoding == "utf-8":
            summary["contents"] = contents
        inspection.decoded_files.append(summary)

    if inspection.total_bytes > MAX_SKILL_BUNDLE_BYTES:
        inspection.hard_findings.append(
            validation_finding("invalid-bundle", "Bundle exceeds the 16 MiB decoded limit.")
        )
    roots = [item for item in inspection.decoded_files if item["path"] == "SKILL.md"]
    if len(roots) != 1:
        inspection.hard_findings.append(
            validation_finding(
                "resolver-incompatible", "Bundle must contain exactly one root SKILL.md."
            )
        )
        return inspection
    root = roots[0]
    root_contents = root.get("contents")
    if not isinstance(root_contents, str):
        inspection.hard_findings.append(
            validation_finding("resolver-incompatible", "SKILL.md must be UTF-8 text.")
        )
        return inspection
    if root_contents != target.skill_md:
        inspection.hard_findings.append(
            validation_finding(
                "invalid-bundle", "Snapshot root content does not match bundled SKILL.md."
            )
        )
    if not root_contents or len(root_contents) > MAX_ROOT_SKILL_CHARS:
        inspection.hard_findings.append(
            validation_finding("resolver-incompatible", "SKILL.md exceeds resolver limits.")
        )
    if not resolver_frontmatter_valid(root_contents):
        inspection.hard_findings.append(
            validation_finding(
                "resolver-incompatible",
                "SKILL.md needs nonempty name and description frontmatter plus instructions.",
            )
        )
    if bundle_content_hash(target.files) != target.content_hash:
        inspection.hard_findings.append(
            validation_finding("invalid-bundle", "Stored bundle does not match its content hash.")
        )
    return inspection


def normalized_finding(finding: CiscoFinding) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in sorted(finding.metadata.items())[:32]:
        if not isinstance(key, str) or len(key) > 128:
            continue
        if isinstance(value, str):
            metadata[key] = value[:1_000]
        elif isinstance(value, (bool, int, float)) or value is None:
            metadata[key] = value
    return {
        "id": finding.id or finding.rule_id or "CISCO-UNSPECIFIED",
        "ruleId": finding.rule_id or finding.id or "CISCO_UNSPECIFIED",
        "category": finding.category,
        "severity": finding.severity,
        "title": finding.title,
        "description": finding.description,
        "filePath": finding.file_path,
        "lineNumber": finding.line_number,
        "snippet": finding.snippet,
        "remediation": finding.remediation,
        "analyzer": finding.analyzer,
        "metadata": metadata,
    }


def score_rank(score: int) -> str:
    if score >= 99:
        return "S"
    if score >= 88:
        return "A+"
    if score >= 75:
        return "A"
    if score >= 63:
        return "A-"
    if score >= 50:
        return "B+"
    if score >= 38:
        return "B"
    if score >= 25:
        return "B-"
    if score >= 13:
        return "C+"
    return "C"


def score_findings(findings: list[dict[str, Any]]) -> tuple[int, str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for finding in findings:
        category = str(finding.get("category") or "uncategorized")
        grouped.setdefault(category, []).append(finding)
    deductions: list[dict[str, Any]] = []
    severity_order = {"safe": 0, "info": 1, "low": 2, "medium": 3, "high": 4, "critical": 5}
    maximum = "safe"
    total = 0
    for category, category_findings in sorted(grouped.items()):
        severities = [str(item.get("severity", "info")) for item in category_findings]
        category_max = max(severities, key=lambda item: severity_order.get(item, 1))
        if severity_order.get(category_max, 1) > severity_order[maximum]:
            maximum = category_max
        # The first issue pays the full severity cost. Repeated issues in the
        # same category still deduct points, at one quarter cost, so noisy
        # rules cannot dominate the score while no finding becomes free.
        points = SEVERITY_DEDUCTIONS.get(category_max, 1)
        remaining_severities = list(severities)
        remaining_severities.remove(category_max)
        points += sum(
            max(1, SEVERITY_DEDUCTIONS.get(severity, 1) // 4) for severity in remaining_severities
        )
        points = min(points, 100)
        total += points
        deductions.append(
            {
                "category": category,
                "points": points,
                "findingCount": len(category_findings),
                "maxSeverity": category_max,
            }
        )
    score = max(0, 100 - total)
    cap = SEVERITY_SCORE_CAPS.get(maximum)
    if cap is not None and score > cap:
        deductions.append(
            {
                "category": f"{maximum}-severity-cap",
                "points": score - cap,
                "findingCount": 0,
                "maxSeverity": maximum,
            }
        )
        score = cap
    return score, score_rank(score), deductions


def stored_scanner_audit(
    target: SkillAuditTarget,
    payload: CiscoScanPayload,
    *,
    llm_enabled: bool,
    configuration_hash: str,
) -> StoredAudit:
    scanner_metadata = payload.scan_metadata
    fingerprint = str(scanner_metadata.get("policy_fingerprint_sha256", ""))
    if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise UserFacingError("Cisco scanner omitted a valid policy fingerprint")
    if payload.findings_count != len(payload.findings):
        raise UserFacingError("Cisco scanner returned an inconsistent findings count")

    source_severity_order = {
        "safe": 0,
        "info": 1,
        "low": 2,
        "medium": 3,
        "high": 4,
        "critical": 5,
    }
    reported_maximum = max(
        (item.severity for item in payload.findings),
        key=lambda item: source_severity_order[item],
        default="safe",
    )
    if payload.max_severity != reported_maximum:
        raise UserFacingError("Cisco scanner returned an inconsistent maximum severity")
    if payload.is_safe != (reported_maximum not in {"high", "critical"}):
        raise UserFacingError("Cisco scanner returned an inconsistent safety decision")

    policy_name = str(scanner_metadata.get("policy_name", SCANNER_POLICY))[:120]
    policy_version = str(scanner_metadata.get("policy_version", ""))[:32]
    bounded_scan_metadata = {
        "policy_name": policy_name,
        "policy_version": policy_version,
        "policy_preset_base": str(scanner_metadata.get("policy_preset_base", ""))[:120],
        "policy_fingerprint_sha256": fingerprint,
    }

    failed_analyzers = {str(item.get("analyzer", "unknown")) for item in payload.analyzers_failed}
    if llm_enabled and (
        LLM_ANALYZER not in payload.analyzers_used or LLM_ANALYZER in failed_analyzers
    ):
        raise UserFacingError("Cisco LLM analyzer did not complete; leaving the skill unaudited")

    findings = [normalized_finding(item) for item in payload.findings]
    missing_analyzers = sorted(REQUIRED_LOCAL_ANALYZERS - set(payload.analyzers_used))
    if payload.analyzers_failed or missing_analyzers:
        findings.append(
            {
                "id": "CISCO-ANALYZER-FAILED",
                "ruleId": "CISCO_ANALYZER_FAILED",
                "category": "incomplete-analysis",
                "severity": "medium",
                "title": "One or more scanner analyzers failed",
                "description": "The scan completed with partial analyzer coverage.",
                "filePath": None,
                "lineNumber": None,
                "snippet": None,
                "remediation": "Review scanner diagnostics and rescan the snapshot.",
                "analyzer": "wardn_result_validator",
                "metadata": {
                    "failedAnalyzers": [
                        str(item.get("analyzer", "unknown"))[:128]
                        for item in payload.analyzers_failed[:20]
                    ],
                    "missingAnalyzers": missing_analyzers,
                },
            }
        )
    score, rank, score_deductions = score_findings(findings)
    severity_order = {"safe": 0, "info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    maximum = max((severity_order[item["severity"]] for item in findings), default=0)
    if maximum >= 3:
        status: Literal["pass", "warn", "fail"] = "fail"
        risk: Literal["low", "medium", "high", "critical"] = "critical" if maximum == 4 else "high"
    elif maximum == 2:
        status = "warn"
        risk = "medium"
    else:
        status = "pass"
        risk = "low"
    counts = {level: 0 for level in ("critical", "high", "medium", "low", "info")}
    for item in findings:
        if item["severity"] in counts:
            counts[item["severity"]] += 1
    summary = (
        f"The Cisco audit recorded {len(findings)} finding(s): "
        + ", ".join(f"{count} {level}" for level, count in counts.items() if count)
        if findings
        else "Cisco AI Skill Scanner found no known threat patterns."
    )
    if payload.analyzers_failed or missing_analyzers:
        summary += " One or more analyzers failed, so coverage is incomplete."
    return StoredAudit(
        scanner_name=SCANNER_NAME,
        scanner_version=SCANNER_VERSION,
        policy_name=policy_name,
        policy_version=policy_version,
        policy_fingerprint=fingerprint,
        configuration_hash=configuration_hash,
        status=status,
        summary=summary,
        risk_level=risk,
        score=score,
        rank=rank,
        score_deductions=score_deductions,
        findings=findings[:MAX_STORED_FINDINGS],
        analyzers=list(dict.fromkeys(payload.analyzers_used))[:128],
        scan_duration_ms=payload.duration_ms,
        raw_result={
            "version": 1,
            "snapshotId": str(target.snapshot_id),
            "contentHash": target.content_hash,
            "configurationHash": configuration_hash,
            "scanCompleted": True,
            "scannerSafe": payload.is_safe,
            "scannerMaxSeverity": payload.max_severity,
            "scannerFindingCount": payload.findings_count,
            "storedFindingCount": min(len(findings), MAX_STORED_FINDINGS),
            "score": score,
            "rank": rank,
            "scoreDeductions": score_deductions,
            "analyzersFailed": [
                str(item.get("analyzer", "unknown"))[:128] for item in payload.analyzers_failed[:20]
            ],
            "missingAnalyzers": missing_analyzers,
            "scanMetadata": bounded_scan_metadata,
        },
    )


class CiscoSkillScanner:
    def __init__(
        self,
        *,
        timeout_seconds: int = 300,
        llm_enabled: bool,
        configuration_hash: str,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.llm_enabled = llm_enabled
        self.configuration_hash = configuration_hash

    def scan(self, target: SkillAuditTarget, inspection: BundleInspection) -> StoredAudit:
        try:
            installed_version = version(SCANNER_DISTRIBUTION)
        except PackageNotFoundError as exc:
            raise UserFacingError(f"{SCANNER_DISTRIBUTION} is not installed") from exc
        if installed_version != SCANNER_VERSION:
            raise UserFacingError(
                f"expected {SCANNER_DISTRIBUTION} {SCANNER_VERSION}, found {installed_version}"
            )
        with tempfile.TemporaryDirectory(prefix="wardn-skill-audit-") as directory:
            root = Path(directory) / "bundle"
            root.mkdir()
            report_path = Path(directory) / "scan.json"
            executable_paths = {
                item["path"] for item in inspection.decoded_files if item["executable"]
            }
            for relative, contents in inspection.materialized_files.items():
                destination = root.joinpath(*PurePosixPath(relative).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(contents)
                if relative in executable_paths:
                    destination.chmod(destination.stat().st_mode | stat.S_IXUSR)
            command = [
                sys.executable,
                "-m",
                "skill_scanner.cli.cli",
                "scan",
                str(root),
                "--policy",
                SCANNER_POLICY,
                "--format",
                "json",
                "--compact",
                "--output-json",
                str(report_path),
            ]
            if SCANNER_BEHAVIORAL_ENABLED:
                command.append("--use-behavioral")
            if self.llm_enabled:
                command.append("--use-llm")
            try:
                result = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    timeout=self.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                raise UserFacingError(
                    f"Cisco scanner timed out after {self.timeout_seconds} seconds"
                ) from exc
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            if result.returncode != 0:
                detail = stderr[-2_000:]
                raise UserFacingError(
                    f"Cisco scanner failed: {detail or f'exit {result.returncode}'}"
                )
            try:
                report_size = report_path.stat().st_size
            except FileNotFoundError as exc:
                raise UserFacingError("Cisco scanner did not produce its JSON report") from exc
            if report_size > MAX_SCANNER_OUTPUT_BYTES:
                raise UserFacingError("Cisco scanner JSON exceeds the 10 MiB output limit")
            try:
                report = report_path.read_bytes()
                payload = CiscoScanPayload.model_validate_json(report)
            except (OSError, ValidationError) as exc:
                detail = str(exc).splitlines()[0][:500]
                raise UserFacingError(
                    f"Cisco scanner returned invalid JSON report: {detail}"
                ) from exc
        return stored_scanner_audit(
            target,
            payload,
            llm_enabled=self.llm_enabled,
            configuration_hash=self.configuration_hash,
        )


def print_stats(stats: AuditStats, stdout: TextIO) -> None:
    print(
        "skill audits: "
        f"seen={stats.seen} pass={stats.passed} warn={stats.warned} "
        f"fail={stats.failed} errors={stats.errors} stale={stats.stale}",
        file=stdout,
    )


def audit_skills(
    *,
    client: SkillAuditDatabaseClient,
    scanner: SkillScanner,
    max_skills: int | None,
    skill_id: str | None,
    re_audit: bool,
    dry_run: bool,
    stdout: TextIO,
) -> int:
    cursor: uuid.UUID | None = None
    stats = AuditStats()
    while max_skills is None or stats.seen < max_skills:
        target = client.next_target(
            after_skill_id=cursor,
            skill_id=skill_id,
            re_audit=re_audit,
        )
        if target is None:
            break
        cursor = target.skill_id
        stats.seen += 1
        print(
            f"Auditing {target.catalog_id} at {target.content_hash} ({len(target.files)} files).",
            file=stdout,
            flush=True,
        )
        inspection = inspect_bundle(target)
        try:
            if inspection.hard_findings:
                raise UserFacingError(
                    "stored package failed safe materialization; refresh its source package"
                )
            audit = scanner.scan(target, inspection)
        except UserFacingError as exc:
            stats.errors += 1
            print(
                f"Audit failed for {target.catalog_id}; leaving it unaudited: {exc}",
                file=stdout,
            )
            continue

        if audit.status == "fail":
            stats.failed += 1
        elif audit.status == "warn":
            stats.warned += 1
        else:
            stats.passed += 1
        if dry_run:
            print(
                f"Dry run: {audit.status}/{audit.risk_level}; no audit stored.",
                file=stdout,
            )
            if skill_id:
                break
            continue

        save_status = client.save_audit(target, audit, re_audit=re_audit)
        if save_status == "stale":
            stats.stale += 1
            print(
                f"Skipped stale audit for {target.catalog_id}; its snapshot changed during scan.",
                file=stdout,
            )
            continue
        if save_status == "already-audited":
            print(f"Skipped {target.catalog_id}; another worker audited it.", file=stdout)
            continue
        print(f"Stored {audit.status} audit for {target.catalog_id}.", file=stdout)
        if skill_id:
            break

    if stats.seen == 0:
        print("No unaudited current skill snapshots remain.", file=stdout)
    print_stats(stats, stdout)
    return 1 if stats.errors or stats.stale else 0


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def skill_id_argument(value: str) -> str:
    try:
        source, slug = split_skill_id(value)
    except Exception as exc:
        raise argparse.ArgumentTypeError("must look like owner/repository/skill-slug") from exc
    return f"{source}/{slug}"


def add_audit_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--skill-id",
        type=skill_id_argument,
        default=None,
        help="Audit exactly one catalog skill ID in owner/repository/slug form.",
    )
    parser.add_argument(
        "--max-skills",
        type=positive_int,
        default=None,
        help="Stop after visiting this many current skill snapshots.",
    )
    parser.add_argument(
        "--reaudit",
        action="store_true",
        help="Rescan matching current snapshots even when their audit is current.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the complete Cisco scan without database writes.",
    )
    parser.add_argument(
        "--scanner-timeout",
        type=positive_int,
        default=DEFAULT_SCANNER_TIMEOUT_SECONDS,
        help="Seconds to wait for each Cisco scan.",
    )


def audit_pending_skill_snapshots(
    *,
    scanner_timeout: int = DEFAULT_SCANNER_TIMEOUT_SECONDS,
    max_skills: int | None = None,
    skill_id: str | None = None,
    re_audit: bool = False,
    dry_run: bool = False,
    stdout: TextIO = sys.stdout,
) -> int:
    settings = get_settings()
    if not settings.skill_audit_enabled:
        raise UserFacingError(
            "skill audits are disabled; set WARDN_HUB_SKILL_AUDIT_ENABLED=true to enable them"
        )
    configuration_hash = current_audit_configuration_hash()
    client = WardnHubDatabaseSkillAuditClient()
    try:
        return audit_skills(
            client=client,
            scanner=CiscoSkillScanner(
                timeout_seconds=scanner_timeout,
                llm_enabled=settings.skill_audit_llm_enabled,
                configuration_hash=configuration_hash,
            ),
            max_skills=max_skills,
            skill_id=skill_id.strip() if skill_id else None,
            re_audit=re_audit,
            dry_run=dry_run,
            stdout=stdout,
        )
    finally:
        client.close()


def audit_skills_from_args(args: argparse.Namespace) -> int:
    return audit_pending_skill_snapshots(
        scanner_timeout=args.scanner_timeout,
        max_skills=args.max_skills,
        skill_id=args.skill_id,
        re_audit=args.reaudit,
        dry_run=args.dry_run,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Scan current public skill snapshots with the Cisco AI Skill Scanner.")
    )
    add_audit_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        return audit_skills_from_args(build_parser().parse_args(argv))
    except UserFacingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
