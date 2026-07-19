"""Replace provider audits with one reproducible scanner result per snapshot.

Revision ID: 202607190003
Revises: 202607190002
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607190003"
down_revision: str | Sequence[str] | None = "202607190002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Previous rows mix deterministic checks with LLM opinions and cannot be
    # compared with the Cisco scanner. Clearing them makes every current
    # snapshot eligible for one reproducible scan under the new policy.
    op.execute("DELETE FROM skill_audits")
    op.drop_index("ix_skill_audits_completion", table_name="skill_audits")
    op.drop_index(op.f("ix_skill_audits_slug"), table_name="skill_audits")
    op.drop_column("skill_audits", "provider")
    op.drop_column("skill_audits", "slug")
    op.drop_column("skill_audits", "categories")

    op.add_column("skill_audits", sa.Column("scanner_name", sa.String(120), nullable=False))
    op.add_column("skill_audits", sa.Column("scanner_version", sa.String(32), nullable=False))
    op.add_column("skill_audits", sa.Column("policy_name", sa.String(120), nullable=False))
    op.add_column(
        "skill_audits",
        sa.Column("policy_version", sa.String(32), server_default="", nullable=False),
    )
    op.add_column(
        "skill_audits",
        sa.Column("policy_fingerprint", sa.String(64), server_default="", nullable=False),
    )
    op.add_column(
        "skill_audits",
        sa.Column("configuration_hash", sa.String(64), nullable=False),
    )
    op.add_column(
        "skill_audits",
        sa.Column("score", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "skill_audits",
        sa.Column("rank", sa.String(8), server_default="C", nullable=False),
    )
    op.add_column(
        "skill_audits",
        sa.Column(
            "score_deductions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "skill_audits",
        sa.Column(
            "findings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "skill_audits",
        sa.Column(
            "analyzers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "skill_audits",
        sa.Column("scan_duration_ms", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index(
        "uq_skill_audits_snapshot_id",
        "skill_audits",
        ["snapshot_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_skill_audits_configuration_hash"),
        "skill_audits",
        ["configuration_hash"],
        unique=False,
    )
    op.create_index(
        "ix_skill_audits_completion",
        "skill_audits",
        ["skill_id", "configuration_hash", "status"],
        unique=False,
    )
    op.create_check_constraint(
        "ck_skill_audits_score_range",
        "skill_audits",
        "score BETWEEN 0 AND 100",
    )
    op.create_check_constraint(
        "ck_skill_audits_status_risk_consistency",
        "skill_audits",
        "(status = 'pass' AND risk_level = 'low') OR "
        "(status = 'warn' AND risk_level = 'medium') OR "
        "(status = 'fail' AND risk_level IN ('high', 'critical'))",
    )
    op.create_check_constraint(
        "ck_skill_audits_rank_score_consistency",
        "skill_audits",
        "(rank = 'S' AND score BETWEEN 99 AND 100) OR "
        "(rank = 'A+' AND score BETWEEN 88 AND 98) OR "
        "(rank = 'A' AND score BETWEEN 75 AND 87) OR "
        "(rank = 'A-' AND score BETWEEN 63 AND 74) OR "
        "(rank = 'B+' AND score BETWEEN 50 AND 62) OR "
        "(rank = 'B' AND score BETWEEN 38 AND 49) OR "
        "(rank = 'B-' AND score BETWEEN 25 AND 37) OR "
        "(rank = 'C+' AND score BETWEEN 13 AND 24) OR "
        "(rank = 'C' AND score BETWEEN 0 AND 12)",
    )
    op.create_check_constraint(
        "ck_skill_audits_severity_score_cap",
        "skill_audits",
        "risk_level = 'low' OR "
        "(risk_level = 'medium' AND score <= 79) OR "
        "(risk_level = 'high' AND score <= 49) OR "
        "(risk_level = 'critical' AND score <= 24)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM skill_audits")
    op.drop_constraint(
        "ck_skill_audits_severity_score_cap",
        "skill_audits",
        type_="check",
    )
    op.drop_constraint(
        "ck_skill_audits_rank_score_consistency",
        "skill_audits",
        type_="check",
    )
    op.drop_constraint(
        "ck_skill_audits_status_risk_consistency",
        "skill_audits",
        type_="check",
    )
    op.drop_constraint(
        "ck_skill_audits_score_range",
        "skill_audits",
        type_="check",
    )
    op.drop_index("ix_skill_audits_completion", table_name="skill_audits")
    op.drop_index(
        op.f("ix_skill_audits_configuration_hash"),
        table_name="skill_audits",
    )
    op.drop_index("uq_skill_audits_snapshot_id", table_name="skill_audits")
    op.drop_column("skill_audits", "scan_duration_ms")
    op.drop_column("skill_audits", "analyzers")
    op.drop_column("skill_audits", "findings")
    op.drop_column("skill_audits", "score_deductions")
    op.drop_column("skill_audits", "rank")
    op.drop_column("skill_audits", "score")
    op.drop_column("skill_audits", "configuration_hash")
    op.drop_column("skill_audits", "policy_fingerprint")
    op.drop_column("skill_audits", "policy_version")
    op.drop_column("skill_audits", "policy_name")
    op.drop_column("skill_audits", "scanner_version")
    op.drop_column("skill_audits", "scanner_name")
    op.add_column("skill_audits", sa.Column("provider", sa.String(120), nullable=False))
    op.add_column("skill_audits", sa.Column("slug", sa.String(120), nullable=False))
    op.add_column(
        "skill_audits",
        sa.Column(
            "categories",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index(op.f("ix_skill_audits_slug"), "skill_audits", ["slug"], unique=False)
    op.create_index(
        "ix_skill_audits_completion",
        "skill_audits",
        ["skill_id", "snapshot_id", "slug", "status"],
        unique=False,
    )
