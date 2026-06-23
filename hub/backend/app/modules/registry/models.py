import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class RegistryServer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_servers"
    __table_args__ = (UniqueConstraint("name", name="uq_mcp_servers_name"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    owner_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    documentation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    website_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    repository: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    icons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    status_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    visibility: Mapped[str] = mapped_column(
        String(32),
        default="public",
        nullable=False,
        index=True,
    )


class RegistryServerVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_server_versions"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_mcp_server_versions_name_version"),
        UniqueConstraint("server_id", "version", name="uq_mcp_server_versions_server_version"),
    )

    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    owner_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    documentation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    website_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    repository: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    packages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    remotes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    icons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    server_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    status_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    publisher_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class RegistryCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_categories"
    __table_args__ = (UniqueConstraint("slug", name="uq_mcp_categories_slug"),)

    slug: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)


class RegistryServerCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_server_categories"
    __table_args__ = (
        UniqueConstraint(
            "server_id",
            "category_id",
            name="uq_mcp_server_categories_server_category",
        ),
    )

    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_categories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(32), default="metadata", nullable=False)
