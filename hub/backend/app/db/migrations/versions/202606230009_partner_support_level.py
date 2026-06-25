"""partner support level

Revision ID: 202606230009
Revises: 202606230008
Create Date: 2026-06-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606230009"
down_revision: str | Sequence[str] | None = "202606230008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "partner_support_level",
            sa.String(length=32),
            server_default="compatible",
            nullable=False,
        ),
    )
    op.create_index(
        op.f("ix_organizations_partner_support_level"),
        "organizations",
        ["partner_support_level"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_organizations_partner_support_level"), table_name="organizations")
    op.drop_column("organizations", "partner_support_level")
