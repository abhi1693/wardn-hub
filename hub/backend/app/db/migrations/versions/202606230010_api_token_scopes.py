"""api token scopes

Revision ID: 202606230010
Revises: 202606230009
Create Date: 2026-06-23 00:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606230010"
down_revision: str | Sequence[str] | None = "202606230009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFAULT_SCOPES = '["catalog:read", "submissions:read", "submissions:write"]'


def upgrade() -> None:
    op.add_column(
        "user_api_tokens",
        sa.Column(
            "scopes",
            sa.JSON(),
            server_default=sa.text(f"'{DEFAULT_SCOPES}'::json"),
            nullable=False,
        ),
    )
    op.alter_column("user_api_tokens", "scopes", server_default=None)


def downgrade() -> None:
    op.drop_column("user_api_tokens", "scopes")
