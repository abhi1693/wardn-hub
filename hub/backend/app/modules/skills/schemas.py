from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SkillSourceType = Literal["github", "well-known"]
SkillStatus = Literal["active", "deprecated", "deleted", "quarantined"]
SkillVisibility = Literal["public", "unlisted", "private_preview"]
SkillAuditStatus = Literal["pass", "warn", "fail"]
SkillAuditSeverity = Literal["safe", "info", "low", "medium", "high", "critical"]
SkillAuditRiskLevel = Literal["low", "medium", "high", "critical"]
SkillAuditRank = Literal["S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C"]
SkillFileEncoding = Literal["utf-8", "base64"]
SkillResolutionStatus = Literal["complete", "incomplete", "pending"]


class SkillRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    slug: str
    name: str
    source: str
    source_type: str = Field(alias="sourceType")
    source_owner: str = Field(default="", alias="sourceOwner")
    source_name: str = Field(default="", alias="sourceName")
    source_owner_url: str | None = Field(default=None, alias="sourceOwnerUrl")
    source_owner_icon_url: str | None = Field(default=None, alias="sourceOwnerIconUrl")
    source_url: str | None = Field(default=None, alias="sourceUrl")
    install_url: str | None = Field(default=None, alias="installUrl")
    url: str
    description: str = ""
    installs: int = Field(ge=0)
    is_official: bool = Field(default=False, alias="isOfficial")
    audit_status: SkillAuditStatus | None = Field(default=None, alias="auditStatus")
    audit_score: int | None = Field(default=None, alias="auditScore", ge=0, le=100)
    audit_rank: SkillAuditRank | None = Field(default=None, alias="auditRank")


class SkillPagination(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page: int
    per_page: int = Field(alias="perPage")
    total: int
    has_more: bool = Field(alias="hasMore")


class SkillListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: list[SkillRead]
    pagination: SkillPagination
    audit_enabled: bool = Field(alias="auditEnabled")


class SkillSearchResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: list[SkillRead]
    query: str
    search_type: str = Field(alias="searchType")
    count: int
    has_more: bool = Field(alias="hasMore")
    next_cursor: str | None = Field(alias="nextCursor")
    duration_ms: int = Field(alias="durationMs")
    audit_enabled: bool = Field(alias="auditEnabled")


class SkillFileRead(BaseModel):
    path: str
    contents: str
    encoding: SkillFileEncoding = Field(
        default="utf-8",
        exclude_if=lambda value: value == "utf-8",
    )
    executable: bool = Field(default=False, exclude_if=lambda value: not value)


class SkillResolutionIssueRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_path: str = Field(alias="sourcePath")
    target: str
    reason: str
    required: bool


class SkillDetailResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str
    slug: str
    source_owner: str = Field(default="", alias="sourceOwner")
    source_name: str = Field(default="", alias="sourceName")
    source_owner_url: str | None = Field(default=None, alias="sourceOwnerUrl")
    source_owner_icon_url: str | None = Field(default=None, alias="sourceOwnerIconUrl")
    source_url: str | None = Field(default=None, alias="sourceUrl")
    hash: str | None = None
    files: list[SkillFileRead] | None = None
    bundle_format_version: int | None = Field(default=None, alias="bundleFormatVersion")
    source_commit_sha: str | None = Field(default=None, alias="sourceCommitSha")
    source_entrypoint: str | None = Field(default=None, alias="sourceEntrypoint")
    resolution_status: SkillResolutionStatus | None = Field(default=None, alias="resolutionStatus")
    resolution_issues: list[SkillResolutionIssueRead] = Field(
        default_factory=list, alias="resolutionIssues"
    )
    audit_enabled: bool = Field(alias="auditEnabled")


class SkillAuditFindingRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    rule_id: str = Field(alias="ruleId")
    category: str
    severity: SkillAuditSeverity
    title: str
    description: str
    file_path: str | None = Field(default=None, alias="filePath")
    line_number: int | None = Field(default=None, alias="lineNumber")
    snippet: str | None = None
    remediation: str | None = None
    analyzer: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillAuditScoreDeductionRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: str
    points: int = Field(ge=0, le=100)
    finding_count: int = Field(alias="findingCount", ge=0)
    max_severity: SkillAuditSeverity = Field(alias="maxSeverity")


class SkillAuditRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    scanner_name: str = Field(alias="scannerName")
    scanner_version: str = Field(alias="scannerVersion")
    policy_name: str = Field(alias="policyName")
    policy_version: str = Field(alias="policyVersion")
    policy_fingerprint: str = Field(
        alias="policyFingerprint",
        pattern=r"^(?:|[a-f0-9]{64})$",
    )
    status: SkillAuditStatus
    summary: str
    audited_at: datetime = Field(alias="auditedAt")
    risk_level: SkillAuditRiskLevel = Field(alias="riskLevel")
    score: int = Field(ge=0, le=100)
    rank: SkillAuditRank
    score_deductions: list[SkillAuditScoreDeductionRead] = Field(alias="scoreDeductions")
    categories: list[str] | None = None
    findings: list[SkillAuditFindingRead] = Field(default_factory=list)
    analyzers: list[str] = Field(default_factory=list)
    scan_duration_ms: int = Field(alias="scanDurationMs", ge=0)

    @model_validator(mode="after")
    def validate_decision(self) -> "SkillAuditRead":
        expected_status = {
            "low": "pass",
            "medium": "warn",
            "high": "fail",
            "critical": "fail",
        }[self.risk_level]
        if self.status != expected_status:
            raise ValueError("audit status is inconsistent with its risk level")
        expected_rank = next(
            rank
            for minimum, rank in (
                (99, "S"),
                (88, "A+"),
                (75, "A"),
                (63, "A-"),
                (50, "B+"),
                (38, "B"),
                (25, "B-"),
                (13, "C+"),
                (0, "C"),
            )
            if self.score >= minimum
        )
        if self.rank != expected_rank:
            raise ValueError("audit rank is inconsistent with its score")
        score_cap = {"medium": 79, "high": 49, "critical": 24}.get(self.risk_level)
        if score_cap is not None and self.score > score_cap:
            raise ValueError("audit score exceeds its severity cap")
        return self


class SkillAuditResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str
    slug: str
    content_hash: str = Field(alias="contentHash", pattern=r"^[a-f0-9]{64}$")
    audit: SkillAuditRead


class OfficialSkillOwner(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    owner: str
    source_owner_icon_url: str | None = Field(default=None, alias="sourceOwnerIconUrl")
    owner_url: str | None = Field(default=None, alias="ownerUrl")
    featured_repo: str = Field(alias="featuredRepo")
    featured_skill: str = Field(alias="featuredSkill")
    skills: list[SkillRead]


class SkillOfficialResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: list[OfficialSkillOwner]
    total_owners: int = Field(alias="totalOwners")
    total_skills: int = Field(alias="totalSkills")
    generated_at: datetime = Field(alias="generatedAt")
    audit_enabled: bool = Field(alias="auditEnabled")


class SkillGitHubImportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    repository_url: str = Field(
        alias="repositoryUrl",
        min_length=1,
        max_length=2048,
        description="GitHub repository URL to scan for SKILL.md files.",
    )


class SkillGitHubImportResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: str
    imported_skill_count: int = Field(alias="importedSkillCount", ge=0)
    skill_ids: list[str] = Field(alias="skillIds")


class SkillSnapshotCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_type: SkillSourceType = Field(default="github", alias="sourceType")
    source: str
    source_owner: str = Field(default="", alias="sourceOwner")
    source_name: str = Field(default="", alias="sourceName")
    source_owner_url: str = Field(default="", alias="sourceOwnerUrl")
    source_owner_icon_url: str = Field(default="", alias="sourceOwnerIconUrl")
    source_url: str = Field(default="", alias="sourceUrl")
    slug: str
    name: str
    description: str = ""
    install_url: str = Field(default="", alias="installUrl")
    website_url: str = Field(default="", alias="websiteUrl")
    repository: dict[str, Any] | None = None
    content_hash: str | None = Field(default=None, alias="contentHash")
    skill_md: str = Field(default="", alias="skillMd")
    metadata: dict[str, Any] = Field(default_factory=dict)
    files: list[SkillFileRead] = Field(default_factory=list)
