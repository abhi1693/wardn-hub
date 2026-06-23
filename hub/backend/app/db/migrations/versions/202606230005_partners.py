"""partners

Revision ID: 202606230005
Revises: 202606230004
Create Date: 2026-06-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606230005"
down_revision: str | Sequence[str] | None = "202606230004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def uuid_pk_column() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False)


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("is_partner", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "organizations",
        sa.Column("partner_status", sa.String(length=32), server_default="none", nullable=False),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "partner_tier",
            sa.String(length=32),
            server_default="community",
            nullable=False,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("website_url", sa.String(length=2048), server_default="", nullable=False),
    )
    op.add_column(
        "organizations",
        sa.Column("support_email", sa.String(length=320), server_default="", nullable=False),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "partner_profile",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("partner_internal_notes", sa.Text(), server_default="", nullable=False),
    )
    op.create_index(op.f("ix_organizations_is_partner"), "organizations", ["is_partner"])
    op.create_index(
        op.f("ix_organizations_partner_status"),
        "organizations",
        ["partner_status"],
    )
    op.create_index(op.f("ix_organizations_partner_tier"), "organizations", ["partner_tier"])

    op.create_table(
        "organization_server_support",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("server_name", sa.String(length=200), nullable=False),
        sa.Column("support_level", sa.String(length=32), nullable=False),
        sa.Column("support_status", sa.String(length=32), nullable=False),
        sa.Column("support_url", sa.String(length=2048), nullable=False),
        sa.Column("docs_url", sa.String(length=2048), nullable=False),
        sa.Column("contact_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("internal_notes", sa.Text(), nullable=False),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "server_name",
            name="uq_organization_server_support_org_server",
        ),
    )
    op.create_index(
        op.f("ix_organization_server_support_organization_id"),
        "organization_server_support",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_organization_server_support_server_name"),
        "organization_server_support",
        ["server_name"],
    )
    op.create_index(
        op.f("ix_organization_server_support_support_level"),
        "organization_server_support",
        ["support_level"],
    )
    op.create_index(
        op.f("ix_organization_server_support_support_status"),
        "organization_server_support",
        ["support_status"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_organization_server_support_support_status"),
        table_name="organization_server_support",
    )
    op.drop_index(
        op.f("ix_organization_server_support_support_level"),
        table_name="organization_server_support",
    )
    op.drop_index(
        op.f("ix_organization_server_support_server_name"),
        table_name="organization_server_support",
    )
    op.drop_index(
        op.f("ix_organization_server_support_organization_id"),
        table_name="organization_server_support",
    )
    op.drop_table("organization_server_support")

    op.drop_index(op.f("ix_organizations_partner_tier"), table_name="organizations")
    op.drop_index(op.f("ix_organizations_partner_status"), table_name="organizations")
    op.drop_index(op.f("ix_organizations_is_partner"), table_name="organizations")
    op.drop_column("organizations", "partner_internal_notes")
    op.drop_column("organizations", "partner_profile")
    op.drop_column("organizations", "support_email")
    op.drop_column("organizations", "website_url")
    op.drop_column("organizations", "partner_tier")
    op.drop_column("organizations", "partner_status")
    op.drop_column("organizations", "is_partner")
