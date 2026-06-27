"""events pipeline

Revision ID: 202606270001
Revises: 202606230012
Create Date: 2026-06-27 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606270001"
down_revision: str | Sequence[str] | None = "202606230012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def uuid_pk_column() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False)


def timestamp_columns() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "event_records",
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("subject_type", sa.String(length=100), nullable=False),
        sa.Column("subject_id", sa.String(length=100), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("visibility_scope", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        uuid_pk_column(),
        sa.ForeignKeyConstraint(["actor_token_id"], ["user_api_tokens.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["owner_organization_id"],
            ["organizations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_event_records_actor_token_id"), "event_records", ["actor_token_id"])
    op.create_index(op.f("ix_event_records_actor_user_id"), "event_records", ["actor_user_id"])
    op.create_index(op.f("ix_event_records_created_at"), "event_records", ["created_at"])
    op.create_index(op.f("ix_event_records_event_type"), "event_records", ["event_type"])
    op.create_index(
        op.f("ix_event_records_owner_organization_id"),
        "event_records",
        ["owner_organization_id"],
    )
    op.create_index(op.f("ix_event_records_owner_user_id"), "event_records", ["owner_user_id"])
    op.create_index(op.f("ix_event_records_subject_id"), "event_records", ["subject_id"])
    op.create_index(op.f("ix_event_records_subject_type"), "event_records", ["subject_type"])

    op.create_table(
        "event_rules",
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("event_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("action_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["owner_organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_event_rules_action_type"), "event_rules", ["action_type"])
    op.create_index(
        op.f("ix_event_rules_created_by_user_id"),
        "event_rules",
        ["created_by_user_id"],
    )
    op.create_index(op.f("ix_event_rules_is_enabled"), "event_rules", ["is_enabled"])
    op.create_index(
        op.f("ix_event_rules_last_triggered_at"),
        "event_rules",
        ["last_triggered_at"],
    )
    op.create_index(
        op.f("ix_event_rules_owner_organization_id"),
        "event_rules",
        ["owner_organization_id"],
    )
    op.create_index(op.f("ix_event_rules_owner_user_id"), "event_rules", ["owner_user_id"])

    op.create_table(
        "event_deliveries",
        sa.Column("event_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_rule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("destination_type", sa.String(length=32), nullable=False),
        sa.Column("destination_url_redacted", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("request_headers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["event_record_id"], ["event_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_rule_id"], ["event_rules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_event_deliveries_destination_type"),
        "event_deliveries",
        ["destination_type"],
    )
    op.create_index(
        op.f("ix_event_deliveries_event_record_id"),
        "event_deliveries",
        ["event_record_id"],
    )
    op.create_index(
        op.f("ix_event_deliveries_event_rule_id"),
        "event_deliveries",
        ["event_rule_id"],
    )
    op.create_index(
        op.f("ix_event_deliveries_next_attempt_at"),
        "event_deliveries",
        ["next_attempt_at"],
    )
    op.create_index(op.f("ix_event_deliveries_status"), "event_deliveries", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_event_deliveries_status"), table_name="event_deliveries")
    op.drop_index(op.f("ix_event_deliveries_next_attempt_at"), table_name="event_deliveries")
    op.drop_index(op.f("ix_event_deliveries_event_rule_id"), table_name="event_deliveries")
    op.drop_index(op.f("ix_event_deliveries_event_record_id"), table_name="event_deliveries")
    op.drop_index(op.f("ix_event_deliveries_destination_type"), table_name="event_deliveries")
    op.drop_table("event_deliveries")

    op.drop_index(op.f("ix_event_rules_owner_user_id"), table_name="event_rules")
    op.drop_index(op.f("ix_event_rules_owner_organization_id"), table_name="event_rules")
    op.drop_index(op.f("ix_event_rules_last_triggered_at"), table_name="event_rules")
    op.drop_index(op.f("ix_event_rules_is_enabled"), table_name="event_rules")
    op.drop_index(op.f("ix_event_rules_created_by_user_id"), table_name="event_rules")
    op.drop_index(op.f("ix_event_rules_action_type"), table_name="event_rules")
    op.drop_table("event_rules")

    op.drop_index(op.f("ix_event_records_subject_type"), table_name="event_records")
    op.drop_index(op.f("ix_event_records_subject_id"), table_name="event_records")
    op.drop_index(op.f("ix_event_records_owner_user_id"), table_name="event_records")
    op.drop_index(op.f("ix_event_records_owner_organization_id"), table_name="event_records")
    op.drop_index(op.f("ix_event_records_event_type"), table_name="event_records")
    op.drop_index(op.f("ix_event_records_created_at"), table_name="event_records")
    op.drop_index(op.f("ix_event_records_actor_user_id"), table_name="event_records")
    op.drop_index(op.f("ix_event_records_actor_token_id"), table_name="event_records")
    op.drop_table("event_records")
