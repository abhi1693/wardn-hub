"""Add existing category assignments for skills.

Revision ID: 202608020001
Revises: 202607300001
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202608020001"
down_revision: str | Sequence[str] | None = "202607300001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skill_categories",
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["category_id"], ["mcp_categories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "skill_id",
            "category_id",
            name="uq_skill_categories_skill_category",
        ),
    )
    op.create_index(
        "ix_skill_categories_category_skill",
        "skill_categories",
        ["category_id", "skill_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_skill_categories_category_id"),
        "skill_categories",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_skill_categories_skill_id"),
        "skill_categories",
        ["skill_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_skill_categories_skill_id"), table_name="skill_categories")
    op.drop_index(op.f("ix_skill_categories_category_id"), table_name="skill_categories")
    op.drop_index("ix_skill_categories_category_skill", table_name="skill_categories")
    op.drop_table("skill_categories")
