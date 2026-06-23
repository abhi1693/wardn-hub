"""submissions audit

Revision ID: 202606230003
Revises: 202606230002
Create Date: 2026-06-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606230003"
down_revision: str | Sequence[str] | None = "202606230002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def uuid_pk_column() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False)


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("subject_type", sa.String(length=100), nullable=False),
        sa.Column("subject_id", sa.String(length=100), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        uuid_pk_column(),
        sa.ForeignKeyConstraint(["actor_token_id"], ["user_api_tokens.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_events_actor_token_id"), "audit_events", ["actor_token_id"])
    op.create_index(op.f("ix_audit_events_actor_user_id"), "audit_events", ["actor_user_id"])
    op.create_index(op.f("ix_audit_events_created_at"), "audit_events", ["created_at"])
    op.create_index(op.f("ix_audit_events_event_type"), "audit_events", ["event_type"])
    op.create_index(op.f("ix_audit_events_organization_id"), "audit_events", ["organization_id"])
    op.create_index(op.f("ix_audit_events_subject_id"), "audit_events", ["subject_id"])
    op.create_index(op.f("ix_audit_events_subject_type"), "audit_events", ["subject_type"])

    op.create_table(
        "server_submissions",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=255), nullable=False),
        sa.Column("submitter_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submission_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("server_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("validation_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approver_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rejection_message", sa.Text(), nullable=False),
        sa.Column("published_server_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["approver_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["owner_organization_id"],
            ["organizations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["published_server_version_id"],
            ["mcp_server_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["submitter_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_server_submissions_approver_user_id"),
        "server_submissions",
        ["approver_user_id"],
    )
    op.create_index(op.f("ix_server_submissions_name"), "server_submissions", ["name"])
    op.create_index(
        op.f("ix_server_submissions_owner_organization_id"),
        "server_submissions",
        ["owner_organization_id"],
    )
    op.create_index(
        op.f("ix_server_submissions_owner_user_id"),
        "server_submissions",
        ["owner_user_id"],
    )
    op.create_index(
        op.f("ix_server_submissions_published_server_version_id"),
        "server_submissions",
        ["published_server_version_id"],
    )
    op.create_index(op.f("ix_server_submissions_status"), "server_submissions", ["status"])
    op.create_index(
        op.f("ix_server_submissions_submission_type"),
        "server_submissions",
        ["submission_type"],
    )
    op.create_index(
        op.f("ix_server_submissions_submitter_user_id"),
        "server_submissions",
        ["submitter_user_id"],
    )
    op.create_index(op.f("ix_server_submissions_version"), "server_submissions", ["version"])


def downgrade() -> None:
    op.drop_index(op.f("ix_server_submissions_version"), table_name="server_submissions")
    op.drop_index(op.f("ix_server_submissions_submitter_user_id"), table_name="server_submissions")
    op.drop_index(op.f("ix_server_submissions_submission_type"), table_name="server_submissions")
    op.drop_index(op.f("ix_server_submissions_status"), table_name="server_submissions")
    op.drop_index(
        op.f("ix_server_submissions_published_server_version_id"),
        table_name="server_submissions",
    )
    op.drop_index(op.f("ix_server_submissions_owner_user_id"), table_name="server_submissions")
    op.drop_index(
        op.f("ix_server_submissions_owner_organization_id"),
        table_name="server_submissions",
    )
    op.drop_index(op.f("ix_server_submissions_name"), table_name="server_submissions")
    op.drop_index(op.f("ix_server_submissions_approver_user_id"), table_name="server_submissions")
    op.drop_table("server_submissions")

    op.drop_index(op.f("ix_audit_events_subject_type"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_subject_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_organization_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_event_type"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_created_at"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_actor_user_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_actor_token_id"), table_name="audit_events")
    op.drop_table("audit_events")
