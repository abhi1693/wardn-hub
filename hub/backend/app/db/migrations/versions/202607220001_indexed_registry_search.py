"""Add indexed full-text search for published MCP servers.

Revision ID: 202607220001
Revises: 202607190006
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607220001"
down_revision: str | Sequence[str] | None = "202607190006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SEARCH_VECTOR_EXPRESSION = """
setweight(to_tsvector('simple'::regconfig, coalesce(name, '')), 'A') ||
setweight(to_tsvector('simple'::regconfig, coalesce(title, '')), 'A') ||
setweight(to_tsvector('english'::regconfig, coalesce(description, '')), 'B') ||
setweight(
    to_tsvector('english'::regconfig, left(coalesce(documentation, ''), 32768)),
    'C'
)
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.add_column(
        "mcp_servers",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR_EXPRESSION, persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_mcp_servers_search_vector",
        "mcp_servers",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.execute(
        "CREATE INDEX ix_mcp_servers_search_name_trgm "
        "ON mcp_servers USING gin (lower(name) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_mcp_servers_search_title_trgm "
        "ON mcp_servers USING gin (lower(title) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_servers_search_title_trgm", table_name="mcp_servers")
    op.drop_index("ix_mcp_servers_search_name_trgm", table_name="mcp_servers")
    op.drop_index("ix_mcp_servers_search_vector", table_name="mcp_servers")
    op.drop_column("mcp_servers", "search_vector")
