"""migrate legacy api token scopes

Revision ID: 202606230012
Revises: 202606230011
Create Date: 2026-06-23 00:12:00.000000

"""
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202606230012"
down_revision: str | Sequence[str] | None = "202606230011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EXPANDED_ADMIN_WRITE_SCOPES = [
    "audit:read",
    "catalog:read",
    "namespaces:write",
    "partners:write",
    "registry:write",
    "submissions:moderate",
    "submissions:publish",
    "submissions:read",
    "submissions:write",
    "tokens:read",
    "tokens:write",
    "users:read",
    "users:write",
]


def upgrade() -> None:
    connection = op.get_bind()
    expanded_scopes = json.dumps(EXPANDED_ADMIN_WRITE_SCOPES)
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text(
                """
                UPDATE user_api_tokens
                SET scopes = CAST(:expanded_scopes AS json)
                WHERE scopes::jsonb ? 'admin:write'
                """
            ),
            {"expanded_scopes": expanded_scopes},
        )
        return

    connection.execute(
        sa.text(
            """
            UPDATE user_api_tokens
            SET scopes = :scopes
            WHERE scopes LIKE '%admin:write%'
            """
        ),
        {"scopes": expanded_scopes},
    )


def downgrade() -> None:
    connection = op.get_bind()
    expanded_scopes = json.dumps(EXPANDED_ADMIN_WRITE_SCOPES)
    legacy_scope = json.dumps(["admin:write"])
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text(
                """
                UPDATE user_api_tokens
                SET scopes = CAST(:legacy_scope AS json)
                WHERE scopes::jsonb = CAST(:expanded_scopes AS jsonb)
                """
            ),
            {
                "expanded_scopes": expanded_scopes,
                "legacy_scope": legacy_scope,
            },
        )
        return

    connection.execute(
        sa.text(
            """
            UPDATE user_api_tokens
            SET scopes = :legacy_scope
            WHERE scopes = :expanded_scopes
            """
        ),
        {
            "expanded_scopes": expanded_scopes,
            "legacy_scope": legacy_scope,
        },
    )
