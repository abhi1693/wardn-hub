"""Remove the unused skill duplicate flag.

Revision ID: 202607190001
Revises: 202607160002
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607190001"
down_revision: str | Sequence[str] | None = "202607160002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_skills_is_duplicate"), table_name="skills")
    op.drop_column("skills", "is_duplicate")


def downgrade() -> None:
    op.add_column(
        "skills",
        sa.Column(
            "is_duplicate",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_index(
        op.f("ix_skills_is_duplicate"),
        "skills",
        ["is_duplicate"],
        unique=False,
    )
    op.alter_column("skills", "is_duplicate", server_default=None)
