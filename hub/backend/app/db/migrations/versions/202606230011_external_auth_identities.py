"""external auth identities

Revision ID: 202606230011
Revises: 202606230010
Create Date: 2026-06-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606230011"
down_revision: str | None = "202606230010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def uuid_pk_column() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False)


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


def upgrade() -> None:
    op.create_table(
        "user_external_identities",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "subject",
            name="uq_user_external_identities_provider_subject",
        ),
    )
    op.create_index(
        op.f("ix_user_external_identities_provider"),
        "user_external_identities",
        ["provider"],
    )
    op.create_index(
        op.f("ix_user_external_identities_user_id"),
        "user_external_identities",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_user_external_identities_user_id"),
        table_name="user_external_identities",
    )
    op.drop_index(
        op.f("ix_user_external_identities_provider"),
        table_name="user_external_identities",
    )
    op.drop_table("user_external_identities")
