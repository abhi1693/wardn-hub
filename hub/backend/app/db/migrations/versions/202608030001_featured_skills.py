"""Add featured flag for skills.

Revision ID: 202608030001
Revises: 202608020001
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608030001"
down_revision: str | Sequence[str] | None = "202608020001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skills",
        sa.Column(
            "is_featured",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_index(op.f("ix_skills_is_featured"), "skills", ["is_featured"], unique=False)
    op.execute(
        """
        UPDATE skills
        SET is_featured = true
        WHERE lower(source_name) = 'wardn-hub'
          AND lower(name) = 'find-skills'
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_skills_is_featured"), table_name="skills")
    op.drop_column("skills", "is_featured")
