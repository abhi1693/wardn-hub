"""registry documentation

Revision ID: 202606230008
Revises: 202606230007
Create Date: 2026-06-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606230008"
down_revision: str | Sequence[str] | None = "202606230007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("documentation", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "mcp_server_versions",
        sa.Column("documentation", sa.Text(), server_default="", nullable=False),
    )
    op.alter_column("mcp_servers", "documentation", server_default=None)
    op.alter_column("mcp_server_versions", "documentation", server_default=None)


def downgrade() -> None:
    op.drop_column("mcp_server_versions", "documentation")
    op.drop_column("mcp_servers", "documentation")
