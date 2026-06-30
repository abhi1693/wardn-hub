"""submission order indexes

Revision ID: 202606300002
Revises: 202606300001
Create Date: 2026-06-30 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606300002"
down_revision: str | Sequence[str] | None = "202606300001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUBMISSION_ORDER_INDEX = "ix_server_submissions_updated_at_id_desc"
SUBMISSION_STATUS_ORDER_INDEX = "ix_server_submissions_status_updated_at_id_desc"


def upgrade() -> None:
    op.create_index(
        SUBMISSION_ORDER_INDEX,
        "server_submissions",
        [sa.text("updated_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        SUBMISSION_STATUS_ORDER_INDEX,
        "server_submissions",
        ["status", sa.text("updated_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index(SUBMISSION_STATUS_ORDER_INDEX, table_name="server_submissions")
    op.drop_index(SUBMISSION_ORDER_INDEX, table_name="server_submissions")
