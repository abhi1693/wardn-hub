"""Bind skill audits to the exact snapshot they reviewed.

Revision ID: 202607160001
Revises: 202607100002
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607160001"
down_revision: str | Sequence[str] | None = "202607100002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skill_audits",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "skill_audits",
        sa.Column("content_hash", sa.String(length=128), nullable=True),
    )
    op.execute(
        """
        UPDATE skill_audits AS audit
        SET snapshot_id = skill.current_snapshot_id,
            content_hash = snapshot.content_hash
        FROM skills AS skill
        JOIN skill_snapshots AS snapshot
          ON snapshot.id = skill.current_snapshot_id
         AND snapshot.skill_id = skill.id
        WHERE audit.skill_id = skill.id
          AND snapshot.content_hash IS NOT NULL
        """
    )
    op.execute(
        "DELETE FROM skill_audits WHERE snapshot_id IS NULL OR content_hash IS NULL"
    )
    op.alter_column("skill_audits", "snapshot_id", nullable=False)
    op.alter_column("skill_audits", "content_hash", nullable=False)
    op.create_foreign_key(
        "fk_skill_audits_snapshot_id_skill_snapshots",
        "skill_audits",
        "skill_snapshots",
        ["snapshot_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_skill_audits_snapshot_id"),
        "skill_audits",
        ["snapshot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_skill_audits_content_hash"),
        "skill_audits",
        ["content_hash"],
        unique=False,
    )
    op.create_index(
        "ix_skill_audits_completion",
        "skill_audits",
        ["skill_id", "snapshot_id", "slug", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_skill_audits_completion", table_name="skill_audits")
    op.drop_index(op.f("ix_skill_audits_content_hash"), table_name="skill_audits")
    op.drop_index(op.f("ix_skill_audits_snapshot_id"), table_name="skill_audits")
    op.drop_constraint(
        "fk_skill_audits_snapshot_id_skill_snapshots",
        "skill_audits",
        type_="foreignkey",
    )
    op.drop_column("skill_audits", "content_hash")
    op.drop_column("skill_audits", "snapshot_id")
