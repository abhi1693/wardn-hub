"""organization icon url

Revision ID: 202607100002
Revises: 202607100001
Create Date: 2026-07-10 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607100002"
down_revision: str | Sequence[str] | None = "202607100001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("icon_url", sa.String(length=2048), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("organizations", "icon_url")
