"""seed mcp categories

Revision ID: 202606230007
Revises: 202606230006
Create Date: 2026-06-23 00:00:00.000000

"""
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "202606230007"
down_revision: str | Sequence[str] | None = "202606230006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CATEGORIES = [
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


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO mcp_categories (id, slug, name, description, sort_order, status)
            VALUES (:id, :slug, :name, :description, :sort_order, 'active')
            ON CONFLICT (slug) DO UPDATE
            SET name = EXCLUDED.name,
                description = EXCLUDED.description,
                sort_order = EXCLUDED.sort_order,
                status = 'active',
                updated_at = now()
            """
        ),
        [
            {
                "id": uuid4(),
                "slug": slug,
                "name": name,
                "description": description,
                "sort_order": sort_order,
            }
            for slug, name, description, sort_order in CATEGORIES
        ],
    )


def downgrade() -> None:
    # Keep categories on downgrade; they may already be referenced by servers.
    pass
