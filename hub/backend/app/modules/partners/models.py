import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class OrganizationServerSupport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_server_support"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "server_name",
            name="uq_organization_server_support_org_server",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    server_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    support_level: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    support_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    support_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    docs_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    contact_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    internal_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
