"""mark orphaned registry servers deleted

Revision ID: 202607040001
Revises: 202607030001
Create Date: 2026-07-04 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = "202607040001"
down_revision: str | Sequence[str] | None = "202607030001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE mcp_servers AS server
        SET status = 'deleted',
            status_message = 'No active published versions remain.',
            current_version_id = NULL,
            updated_at = now()
        WHERE server.status != 'deleted'
          AND NOT EXISTS (
              SELECT 1
              FROM mcp_server_versions AS version
              WHERE version.server_id = server.id
                AND version.status = 'active'
          )
        """
    )


def downgrade() -> None:
    pass
