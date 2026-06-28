"""unique active submissions

Revision ID: 202606280003
Revises: 202606280002
Create Date: 2026-06-28 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606280003"
down_revision: str | Sequence[str] | None = "202606280002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_STATUSES = ("draft", "submitted", "approved", "rejected")
INDEX_NAME = "uq_server_submissions_active_name_version"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY name, version
                        ORDER BY
                            CASE status
                                WHEN 'approved' THEN 0
                                WHEN 'submitted' THEN 1
                                WHEN 'draft' THEN 2
                                WHEN 'rejected' THEN 3
                                ELSE 4
                            END,
                            updated_at DESC NULLS LAST,
                            created_at DESC NULLS LAST,
                            id DESC
                    ) AS duplicate_rank
                FROM server_submissions
                WHERE status IN ('draft', 'submitted', 'approved', 'rejected')
            )
            UPDATE server_submissions
            SET
                status = 'withdrawn',
                rejection_message = CASE
                    WHEN rejection_message IS NULL OR rejection_message = ''
                        THEN 'Withdrawn automatically because another active submission exists '
                            || 'for the same server version.'
                    ELSE rejection_message
                END,
                updated_at = now()
            WHERE id IN (
                SELECT id
                FROM ranked
                WHERE duplicate_rank > 1
            )
            """
        )
    )
    op.create_index(
        INDEX_NAME,
        "server_submissions",
        ["name", "version"],
        unique=True,
        postgresql_where=sa.text("status IN ('draft', 'submitted', 'approved', 'rejected')"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="server_submissions", postgresql_where=None)
