"""registry categories

Revision ID: 202606230006
Revises: 202606230005
Create Date: 2026-06-23 00:00:00.000000

"""
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202606230006"
down_revision: str | Sequence[str] | None = "202606230005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFAULT_CATEGORIES = [
    ("search", "Search", "Search, retrieval, and discovery MCP servers.", 100),
    ("web-scraping", "Web Scraping", "Browser automation, scraping, and extraction servers.", 110),
    (
        "communication",
        "Communication",
        "Messaging, meetings, email, and collaboration servers.",
        120,
    ),
    (
        "productivity",
        "Productivity",
        "Task, calendar, notes, and workflow productivity servers.",
        130,
    ),
    ("marketing", "Marketing", "Marketing, growth, and brand operation servers.", 140),
    ("design", "Design", "Design, creative, media, and asset workflow servers.", 150),
    ("memory", "Memory", "Memory, context, and long-term knowledge servers.", 160),
    ("finance", "Finance", "Financial data, accounting, and market workflow servers.", 170),
    ("development", "Development", "Developer tools, coding agents, and engineering servers.", 180),
    ("database", "Database", "Database, SQL, storage, and data platform servers.", 190),
    ("cloud-service", "Cloud Service", "Cloud provider and infrastructure operation servers.", 200),
    ("file-system", "File System", "Local and remote file system access servers.", 210),
    ("cloud-storage", "Cloud Storage", "Object storage, document storage, and drive servers.", 220),
    (
        "version-control",
        "Version Control",
        "Repository, issue, pull request, and source control servers.",
        230,
    ),
    ("other", "Other", "Servers that do not fit an existing primary category.", 1000),
]


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
        "mcp_categories",
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="1000", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_mcp_categories_slug"),
    )
    op.create_index(op.f("ix_mcp_categories_slug"), "mcp_categories", ["slug"])
    op.create_index(op.f("ix_mcp_categories_status"), "mcp_categories", ["status"])

    op.create_table(
        "mcp_server_categories",
        sa.Column("server_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=32), server_default="metadata", nullable=False),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["category_id"], ["mcp_categories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["server_id"], ["mcp_servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "server_id",
            "category_id",
            name="uq_mcp_server_categories_server_category",
        ),
    )
    op.create_index(
        op.f("ix_mcp_server_categories_category_id"),
        "mcp_server_categories",
        ["category_id"],
    )
    op.create_index(
        op.f("ix_mcp_server_categories_server_id"),
        "mcp_server_categories",
        ["server_id"],
    )

    categories_table = sa.table(
        "mcp_categories",
        sa.column("id", postgresql.UUID),
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("sort_order", sa.Integer),
        sa.column("status", sa.String),
    )
    op.bulk_insert(
        categories_table,
        [
            {
                "id": uuid4(),
                "slug": slug,
                "name": name,
                "description": description,
                "sort_order": sort_order,
                "status": "active",
            }
            for slug, name, description, sort_order in DEFAULT_CATEGORIES
        ],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_mcp_server_categories_server_id"), table_name="mcp_server_categories")
    op.drop_index(op.f("ix_mcp_server_categories_category_id"), table_name="mcp_server_categories")
    op.drop_table("mcp_server_categories")
    op.drop_index(op.f("ix_mcp_categories_status"), table_name="mcp_categories")
    op.drop_index(op.f("ix_mcp_categories_slug"), table_name="mcp_categories")
    op.drop_table("mcp_categories")
