"""event records unprocessed queue index

Revision ID: 202606300001
Revises: 202606280003
Create Date: 2026-06-30 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606300001"
down_revision: str | Sequence[str] | None = "202606280003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_event_records_unprocessed_created_at_id"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "event_records",
        ["created_at", "id"],
        postgresql_where=sa.text("processed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="event_records", postgresql_where=None)
