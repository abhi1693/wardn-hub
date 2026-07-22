"""event metric indexes

Revision ID: 202607220002
Revises: 202607220001
Create Date: 2026-07-22 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607220002"
down_revision: str | Sequence[str] | None = "202607220001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_RECORDS_INDEX = "ix_event_records_event_type_created_at"
EVENT_DELIVERIES_INDEX = "ix_event_deliveries_status_updated_at"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            EVENT_RECORDS_INDEX,
            "event_records",
            ["event_type", "created_at"],
            postgresql_concurrently=True,
        )
        op.create_index(
            EVENT_DELIVERIES_INDEX,
            "event_deliveries",
            ["status", "updated_at"],
            postgresql_include=["destination_type"],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            EVENT_DELIVERIES_INDEX,
            table_name="event_deliveries",
            postgresql_concurrently=True,
        )
        op.drop_index(
            EVENT_RECORDS_INDEX,
            table_name="event_records",
            postgresql_concurrently=True,
        )
