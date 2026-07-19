import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class GitHubHttpCache(Base):
    __tablename__ = "github_http_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    etag: Mapped[str] = mapped_column(Text, nullable=False)
    response_headers: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, nullable=False)
    body: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    body_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
        index=True,
    )


class Skill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("source", "slug", name="uq_skills_source_slug"),
        UniqueConstraint("source_type", "source", "slug", name="uq_skills_source_type_source_slug"),
    )

    source_type: Mapped[str] = mapped_column(String(32), default="github", nullable=False)
    source: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    source_owner: Mapped[str] = mapped_column(String(200), default="", nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(200), default="", nullable=False, index=True)
    source_owner_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    source_owner_icon_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    install_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    website_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    repository: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    repository_subfolder: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    owner_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    current_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    installs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(
        String(32),
        default="public",
        nullable=False,
        index=True,
    )


Index(
    "uq_skills_source_repository_subfolder",
    Skill.source_type,
    func.lower(Skill.source),
    Skill.repository_subfolder,
    unique=True,
    postgresql_where=Skill.repository_subfolder.is_not(None),
)


class SkillSearchDocument(Base):
    __tablename__ = "skill_search_documents"

    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skill_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(300), nullable=False)
    source_owner: Mapped[str] = mapped_column(String(200), nullable=False)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    install_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    file_paths: Mapped[str] = mapped_column(Text, nullable=False)
    installs: Mapped[int] = mapped_column(Integer, nullable=False)
    is_canonical: Mapped[bool] = mapped_column(Boolean, nullable=False)
    identity_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[Any] = mapped_column(TSVECTOR, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


Index(
    "ix_skill_search_documents_exact_id",
    func.lower(SkillSearchDocument.source),
    func.lower(SkillSearchDocument.slug),
    postgresql_where=SkillSearchDocument.is_canonical.is_(True),
)
Index(
    "ix_skill_search_documents_owner",
    func.lower(SkillSearchDocument.source_owner),
    postgresql_where=SkillSearchDocument.is_canonical.is_(True),
)
Index(
    "ix_skill_search_documents_search_vector",
    SkillSearchDocument.search_vector,
    postgresql_using="gin",
    postgresql_where=SkillSearchDocument.is_canonical.is_(True),
)
Index(
    "ix_skill_search_documents_identity_trgm",
    SkillSearchDocument.identity_text,
    postgresql_using="gin",
    postgresql_ops={"identity_text": "gin_trgm_ops"},
    postgresql_where=SkillSearchDocument.is_canonical.is_(True),
)
Index(
    "ix_skill_search_documents_canonical_installs",
    SkillSearchDocument.is_canonical,
    SkillSearchDocument.installs.desc(),
)


class SkillSourceOwner(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skill_source_owners"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_owner",
            name="uq_skill_source_owners_type_owner",
        ),
    )

    source_type: Mapped[str] = mapped_column(String(32), default="github", nullable=False)
    source_owner: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_owner_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    source_owner_icon_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    is_official: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)


class SkillSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skill_snapshots"
    __table_args__ = (
        UniqueConstraint("skill_id", "content_hash", name="uq_skill_snapshots_skill_hash"),
    )

    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    skill_md: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=False,
    )
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    bundle_format_version: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    source_commit_sha: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    source_entrypoint: Mapped[str] = mapped_column(String(2048), default="SKILL.md", nullable=False)
    resolution_status: Mapped[str] = mapped_column(
        String(32), default="complete", nullable=False, index=True
    )
    resolution_issues: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    dependency_manifest: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    publisher_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class SkillAudit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skill_audits"
    __table_args__ = (
        Index("uq_skill_audits_snapshot_id", "snapshot_id", unique=True),
        Index("ix_skill_audits_completion", "skill_id", "configuration_hash", "status"),
        CheckConstraint("score BETWEEN 0 AND 100", name="ck_skill_audits_score_range"),
        CheckConstraint(
            "(status = 'pass' AND risk_level = 'low') OR "
            "(status = 'warn' AND risk_level = 'medium') OR "
            "(status = 'fail' AND risk_level IN ('high', 'critical'))",
            name="ck_skill_audits_status_risk_consistency",
        ),
        CheckConstraint(
            "(rank = 'S' AND score BETWEEN 99 AND 100) OR "
            "(rank = 'A+' AND score BETWEEN 88 AND 98) OR "
            "(rank = 'A' AND score BETWEEN 75 AND 87) OR "
            "(rank = 'A-' AND score BETWEEN 63 AND 74) OR "
            "(rank = 'B+' AND score BETWEEN 50 AND 62) OR "
            "(rank = 'B' AND score BETWEEN 38 AND 49) OR "
            "(rank = 'B-' AND score BETWEEN 25 AND 37) OR "
            "(rank = 'C+' AND score BETWEEN 13 AND 24) OR "
            "(rank = 'C' AND score BETWEEN 0 AND 12)",
            name="ck_skill_audits_rank_score_consistency",
        ),
        CheckConstraint(
            "risk_level = 'low' OR "
            "(risk_level = 'medium' AND score <= 79) OR "
            "(risk_level = 'high' AND score <= 49) OR "
            "(risk_level = 'critical' AND score <= 24)",
            name="ck_skill_audits_severity_score_cap",
        ),
    )

    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skill_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    scanner_name: Mapped[str] = mapped_column(String(120), nullable=False)
    scanner_version: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_name: Mapped[str] = mapped_column(String(120), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    policy_fingerprint: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    score: Mapped[int] = mapped_column(default=0, nullable=False)
    rank: Mapped[str] = mapped_column(String(8), default="C", nullable=False)
    score_deductions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    analyzers: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    scan_duration_ms: Mapped[int] = mapped_column(default=0, nullable=False)
    raw_result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    audited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class SkillInstallEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "skill_install_events"
    __table_args__ = (
        Index("ix_skill_install_events_skill_created", "skill_id", "created_at"),
        Index("ix_skill_install_events_created_skill", "created_at", "skill_id"),
    )

    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skill_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), default="find-skills", nullable=False)
    resolver_version: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
