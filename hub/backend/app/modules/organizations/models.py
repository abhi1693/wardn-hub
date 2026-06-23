import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_partner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    partner_status: Mapped[str] = mapped_column(
        String(32),
        default="none",
        nullable=False,
        index=True,
    )
    partner_tier: Mapped[str] = mapped_column(
        String(32),
        default="community",
        nullable=False,
        index=True,
    )
    website_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    support_email: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    partner_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    partner_internal_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    roles: Mapped[list["OrganizationRole"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    memberships: Mapped[list["OrganizationMembership"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )


class OrganizationRole(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_roles"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "slug",
            name="uq_organization_roles_org_slug",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    permissions: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    is_system_role: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="roles")


class OrganizationMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_organization_memberships_org_user",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_roles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    role: Mapped[OrganizationRole] = relationship()


DEFAULT_ORGANIZATION_ROLES: dict[str, dict[str, Any]] = {
    "owner": {
        "name": "Owner",
        "description": "Full organization control.",
        "permissions": [
            "organization.manage",
            "organization.roles.manage",
            "organization.members.manage",
            "servers.create",
            "servers.update",
            "submissions.approve",
            "namespaces.manage",
            "partner_status.manage",
        ],
    },
    "admin": {
        "name": "Admin",
        "description": "Manage organization-owned server definitions and namespaces.",
        "permissions": ["servers.create", "servers.update", "namespaces.manage"],
    },
    "publisher": {
        "name": "Publisher",
        "description": "Submit and edit server definitions.",
        "permissions": ["servers.create", "servers.update"],
    },
    "approver": {
        "name": "Approver",
        "description": "Approve and publish submitted definitions.",
        "permissions": ["submissions.approve"],
    },
    "member": {
        "name": "Member",
        "description": "Read organization-owned records.",
        "permissions": [],
    },
}
