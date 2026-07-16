import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


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
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    owner_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    current_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    installs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(
        String(32),
        default="public",
        nullable=False,
        index=True,
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
        Index(
            "ix_skill_audits_completion",
            "skill_id",
            "snapshot_id",
            "slug",
            "status",
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
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    categories: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
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
