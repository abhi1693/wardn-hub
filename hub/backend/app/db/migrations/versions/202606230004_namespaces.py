"""namespaces

Revision ID: 202606230004
Revises: 202606230003
Create Date: 2026-06-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606230004"
down_revision: str | Sequence[str] | None = "202606230003"
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
    op.create_table(
        "namespace_claims",
        sa.Column("namespace", sa.String(length=255), nullable=False),
        sa.Column("owner_organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claimed_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("verification_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["claimed_by_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_organization_id"],
            ["organizations.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_namespace_claims_claimed_by_user_id"),
        "namespace_claims",
        ["claimed_by_user_id"],
    )
    op.create_index(op.f("ix_namespace_claims_method"), "namespace_claims", ["method"])
    op.create_index(op.f("ix_namespace_claims_namespace"), "namespace_claims", ["namespace"])
    op.create_index(
        op.f("ix_namespace_claims_owner_organization_id"),
        "namespace_claims",
        ["owner_organization_id"],
    )
    op.create_index(op.f("ix_namespace_claims_status"), "namespace_claims", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_namespace_claims_status"), table_name="namespace_claims")
    op.drop_index(
        op.f("ix_namespace_claims_owner_organization_id"),
        table_name="namespace_claims",
    )
    op.drop_index(op.f("ix_namespace_claims_namespace"), table_name="namespace_claims")
    op.drop_index(op.f("ix_namespace_claims_method"), table_name="namespace_claims")
    op.drop_index(
        op.f("ix_namespace_claims_claimed_by_user_id"),
        table_name="namespace_claims",
    )
    op.drop_table("namespace_claims")
