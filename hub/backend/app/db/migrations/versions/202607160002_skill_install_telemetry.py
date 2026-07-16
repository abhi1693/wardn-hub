"""Add anonymous skill install telemetry.

Revision ID: 202607160002
Revises: 202607160001
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607160002"
down_revision: str | Sequence[str] | None = "202607160001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skill_install_events",
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("resolver_version", sa.String(length=32), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["skill_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_skill_install_events_content_hash"),
        "skill_install_events",
        ["content_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_skill_install_events_skill_id"),
        "skill_install_events",
        ["skill_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_skill_install_events_snapshot_id"),
        "skill_install_events",
        ["snapshot_id"],
        unique=False,
    )
    op.create_index(
        "ix_skill_install_events_skill_created",
        "skill_install_events",
        ["skill_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_skill_install_events_created_skill",
        "skill_install_events",
        ["created_at", "skill_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_skill_install_events_created_skill", table_name="skill_install_events")
    op.drop_index("ix_skill_install_events_skill_created", table_name="skill_install_events")
    op.drop_index(
        op.f("ix_skill_install_events_snapshot_id"),
        table_name="skill_install_events",
    )
    op.drop_index(op.f("ix_skill_install_events_skill_id"), table_name="skill_install_events")
    op.drop_index(
        op.f("ix_skill_install_events_content_hash"),
        table_name="skill_install_events",
    )
    op.drop_table("skill_install_events")
