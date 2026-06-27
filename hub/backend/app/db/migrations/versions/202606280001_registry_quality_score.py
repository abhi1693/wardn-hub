"""registry quality score

Revision ID: 202606280001
Revises: 202606270001
Create Date: 2026-06-28 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606280001"
down_revision: str | Sequence[str] | None = "202606270001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_server_versions",
        sa.Column("quality_score", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_mcp_server_versions_quality_score_range",
        "mcp_server_versions",
        "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 100)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_mcp_server_versions_quality_score_range",
        "mcp_server_versions",
        type_="check",
    )
    op.drop_column("mcp_server_versions", "quality_score")
