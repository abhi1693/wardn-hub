"""Add an idempotent source-path identity for repository skills.

Revision ID: 202607190002
Revises: 202607190001
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607190002"
down_revision: str | Sequence[str] | None = "202607190001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skills",
        sa.Column("repository_subfolder", sa.String(length=2048), nullable=True),
    )
    op.execute(
        """
        UPDATE skills
        SET repository_subfolder = CASE
            WHEN jsonb_typeof(repository -> 'subfolder') = 'string'
                THEN repository ->> 'subfolder'
            WHEN source_type = 'github' AND repository ? 'branch'
                THEN ''
            ELSE NULL
        END
        WHERE repository_subfolder IS NULL
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM skills
                WHERE repository_subfolder IS NOT NULL
                GROUP BY source_type, lower(source), repository_subfolder
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'duplicate skill repository source paths must be resolved before migration';
            END IF;
        END
        $$
        """
    )
    op.create_index(
        "uq_skills_source_repository_subfolder",
        "skills",
        ["source_type", sa.text("lower(source)"), "repository_subfolder"],
        unique=True,
        postgresql_where=sa.text("repository_subfolder IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_skills_source_repository_subfolder",
        table_name="skills",
    )
    op.drop_column("skills", "repository_subfolder")
