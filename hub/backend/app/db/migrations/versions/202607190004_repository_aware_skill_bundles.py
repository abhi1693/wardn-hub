"""Track repository-aware skill packages and their dependency resolution.

Revision ID: 202607190004
Revises: 202607190003
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607190004"
down_revision: str | Sequence[str] | None = "202607190003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skill_snapshots",
        sa.Column("bundle_format_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "skill_snapshots",
        sa.Column("source_commit_sha", sa.String(64), server_default="", nullable=False),
    )
    op.add_column(
        "skill_snapshots",
        sa.Column("source_entrypoint", sa.String(2048), server_default="SKILL.md", nullable=False),
    )
    op.add_column(
        "skill_snapshots",
        sa.Column("resolution_status", sa.String(32), server_default="pending", nullable=False),
    )
    op.add_column(
        "skill_snapshots",
        sa.Column(
            "resolution_issues",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "skill_snapshots",
        sa.Column(
            "dependency_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_skill_snapshots_bundle_format_version",
        "skill_snapshots",
        "bundle_format_version IN (1, 2)",
    )
    op.create_check_constraint(
        "ck_skill_snapshots_resolution_status",
        "skill_snapshots",
        "resolution_status IN ('complete', 'incomplete', 'pending')",
    )
    op.create_index(
        op.f("ix_skill_snapshots_resolution_status"),
        "skill_snapshots",
        ["resolution_status"],
        unique=False,
    )

    # GitHub bundles must be rebuilt from their repositories because older rows
    # only contain a skill-local subtree. Non-GitHub snapshots are already
    # self-contained and can use the v2 contract directly.
    op.execute(
        """
        UPDATE skill_snapshots AS snapshot
        SET bundle_format_version = 2,
            resolution_status = 'complete'
        FROM skills AS skill
        WHERE snapshot.skill_id = skill.id
          AND skill.source_type <> 'github'
        """
    )
    op.alter_column(
        "skill_snapshots", "bundle_format_version", server_default=sa.text("2")
    )
    op.alter_column(
        "skill_snapshots", "resolution_status", server_default=sa.text("'complete'")
    )
    op.execute("DELETE FROM skill_audits")


def downgrade() -> None:
    op.execute("DELETE FROM skill_audits")
    op.drop_index(
        op.f("ix_skill_snapshots_resolution_status"),
        table_name="skill_snapshots",
    )
    op.drop_constraint(
        "ck_skill_snapshots_resolution_status", "skill_snapshots", type_="check"
    )
    op.drop_constraint(
        "ck_skill_snapshots_bundle_format_version", "skill_snapshots", type_="check"
    )
    op.drop_column("skill_snapshots", "dependency_manifest")
    op.drop_column("skill_snapshots", "resolution_issues")
    op.drop_column("skill_snapshots", "resolution_status")
    op.drop_column("skill_snapshots", "source_entrypoint")
    op.drop_column("skill_snapshots", "source_commit_sha")
    op.drop_column("skill_snapshots", "bundle_format_version")
