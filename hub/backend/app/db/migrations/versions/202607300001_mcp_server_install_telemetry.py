"""Add anonymous MCP server install telemetry.

Revision ID: 202607300001
Revises: 202607240002
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607300001"
down_revision: str | Sequence[str] | None = "202607240002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("installs", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "mcp_server_versions",
        sa.Column("installs", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "mcp_server_install_events",
        sa.Column("server_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("client_version", sa.String(length=32), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["server_id"], ["mcp_servers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["mcp_server_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mcp_server_install_events_server_id"),
        "mcp_server_install_events",
        ["server_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_server_install_events_version"),
        "mcp_server_install_events",
        ["version"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mcp_server_install_events_version_id"),
        "mcp_server_install_events",
        ["version_id"],
        unique=False,
    )
    op.create_index(
        "ix_mcp_server_install_events_server_created",
        "mcp_server_install_events",
        ["server_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_mcp_server_install_events_created_server",
        "mcp_server_install_events",
        ["created_at", "server_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mcp_server_install_events_created_server",
        table_name="mcp_server_install_events",
    )
    op.drop_index(
        "ix_mcp_server_install_events_server_created",
        table_name="mcp_server_install_events",
    )
    op.drop_index(
        op.f("ix_mcp_server_install_events_version_id"),
        table_name="mcp_server_install_events",
    )
    op.drop_index(
        op.f("ix_mcp_server_install_events_version"),
        table_name="mcp_server_install_events",
    )
    op.drop_index(
        op.f("ix_mcp_server_install_events_server_id"),
        table_name="mcp_server_install_events",
    )
    op.drop_table("mcp_server_install_events")
    op.drop_column("mcp_server_versions", "installs")
    op.drop_column("mcp_servers", "installs")
