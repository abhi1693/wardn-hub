"""Persist bounded authenticated GitHub conditional responses.

Revision ID: 202607190005
Revises: 202607190004
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607190005"
down_revision: str | Sequence[str] | None = "202607190004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "github_http_cache",
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("etag", sa.Text(), nullable=False),
        sa.Column(
            "response_headers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column("body_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "last_accessed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("cache_key"),
    )
    op.create_index(
        op.f("ix_github_http_cache_last_accessed_at"),
        "github_http_cache",
        ["last_accessed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_github_http_cache_last_accessed_at"),
        table_name="github_http_cache",
    )
    op.drop_table("github_http_cache")
