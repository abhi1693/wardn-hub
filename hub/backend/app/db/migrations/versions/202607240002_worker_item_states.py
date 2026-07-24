"""worker item states

Revision ID: 202607240002
Revises: 202607240001
Create Date: 2026-07-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607240002"
down_revision: str | Sequence[str] | None = "202607240001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RETIRED_AUTOMATION_URLS = (
    "http://wardn-hub-review-webhook.wardn.svc.cluster.local:8090/"
    "webhooks/wardn/submission-review",
    "http://wardn-hub-fix-rejected-webhook.wardn.svc.cluster.local:8091/"
    "webhooks/wardn/rejected-submission-fix",
)


def upgrade() -> None:
    op.create_table(
        "worker_item_states",
        sa.Column("job_name", sa.String(length=64), nullable=False),
        sa.Column("item_id", sa.String(length=256), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=False),
        sa.Column("item_revision", sa.String(length=128), nullable=True),
        sa.Column("item_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_result",
            sa.String(length=32),
            server_default="claimed",
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("job_name", "item_id"),
    )
    op.create_index(
        "ix_worker_item_states_job_retry_claim",
        "worker_item_states",
        ["job_name", "retry_after", "claimed_until"],
    )

    event_rules = sa.table(
        "event_rules",
        sa.column("id", sa.Uuid()),
        sa.column("is_enabled", sa.Boolean()),
        sa.column("action_config", sa.JSON()),
    )
    event_deliveries = sa.table(
        "event_deliveries",
        sa.column("event_rule_id", sa.Uuid()),
        sa.column("status", sa.String()),
        sa.column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.column("error_message", sa.Text()),
    )
    retired_rule_ids = sa.select(event_rules.c.id).where(
        event_rules.c.action_config["url"].as_string().in_(RETIRED_AUTOMATION_URLS)
    )
    op.execute(
        event_rules.update()
        .where(event_rules.c.id.in_(retired_rule_ids))
        .values(is_enabled=False)
    )
    op.execute(
        event_deliveries.update()
        .where(
            event_deliveries.c.event_rule_id.in_(retired_rule_ids),
            event_deliveries.c.status.in_(("pending", "retrying", "running")),
        )
        .values(
            status="disabled",
            next_attempt_at=None,
            error_message="retired application worker automation",
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_worker_item_states_job_retry_claim",
        table_name="worker_item_states",
    )
    op.drop_table("worker_item_states")
