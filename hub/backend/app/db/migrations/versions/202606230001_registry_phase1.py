"""registry phase 1

Revision ID: 202606230001
Revises:
Create Date: 2026-06-23 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606230001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("website_url", sa.String(length=2048), nullable=False),
        sa.Column("repository", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("icons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("status_message", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_mcp_servers_name"),
    )
    op.create_index(op.f("ix_mcp_servers_name"), "mcp_servers", ["name"], unique=False)
    op.create_index(
        op.f("ix_mcp_servers_owner_organization_id"),
        "mcp_servers",
        ["owner_organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_servers_owner_user_id"),
        "mcp_servers",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(op.f("ix_mcp_servers_status"), "mcp_servers", ["status"], unique=False)
    op.create_index(op.f("ix_mcp_servers_visibility"), "mcp_servers", ["visibility"], unique=False)

    op.create_table(
        "mcp_server_versions",
        sa.Column("server_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=255), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("website_url", sa.String(length=2048), nullable=False),
        sa.Column("repository", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("packages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("remotes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("icons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("server_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("status_message", sa.Text(), nullable=False),
        sa.Column("is_latest", sa.Boolean(), nullable=False),
        sa.Column("publisher_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "status_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["server_id"], ["mcp_servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_mcp_server_versions_name_version"),
        sa.UniqueConstraint("server_id", "version", name="uq_mcp_server_versions_server_version"),
    )
    op.create_index(
        op.f("ix_mcp_server_versions_is_latest"),
        "mcp_server_versions",
        ["is_latest"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_server_versions_name"),
        "mcp_server_versions",
        ["name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_server_versions_owner_organization_id"),
        "mcp_server_versions",
        ["owner_organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_server_versions_owner_user_id"),
        "mcp_server_versions",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_server_versions_server_id"),
        "mcp_server_versions",
        ["server_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_server_versions_status"),
        "mcp_server_versions",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_mcp_server_versions_status"), table_name="mcp_server_versions")
    op.drop_index(op.f("ix_mcp_server_versions_server_id"), table_name="mcp_server_versions")
    op.drop_index(
        op.f("ix_mcp_server_versions_owner_user_id"),
        table_name="mcp_server_versions",
    )
    op.drop_index(
        op.f("ix_mcp_server_versions_owner_organization_id"),
        table_name="mcp_server_versions",
    )
    op.drop_index(op.f("ix_mcp_server_versions_name"), table_name="mcp_server_versions")
    op.drop_index(op.f("ix_mcp_server_versions_is_latest"), table_name="mcp_server_versions")
    op.drop_table("mcp_server_versions")
    op.drop_index(op.f("ix_mcp_servers_visibility"), table_name="mcp_servers")
    op.drop_index(op.f("ix_mcp_servers_status"), table_name="mcp_servers")
    op.drop_index(op.f("ix_mcp_servers_owner_user_id"), table_name="mcp_servers")
    op.drop_index(op.f("ix_mcp_servers_owner_organization_id"), table_name="mcp_servers")
    op.drop_index(op.f("ix_mcp_servers_name"), table_name="mcp_servers")
    op.drop_table("mcp_servers")
