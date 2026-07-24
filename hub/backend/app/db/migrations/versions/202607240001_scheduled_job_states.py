"""scheduled job states

Revision ID: 202607240001
Revises: 202607220002
Create Date: 2026-07-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607240001"
down_revision: str | Sequence[str] | None = "202607220002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_job_states",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_status",
            sa.String(length=32),
            server_default="scheduled",
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), server_default="", nullable=False),
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
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_index(
        op.f("ix_scheduled_job_states_next_run_at"),
        "scheduled_job_states",
        ["next_run_at"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_scheduled_job_states_next_run_at"),
        table_name="scheduled_job_states",
    )
    op.drop_table("scheduled_job_states")
