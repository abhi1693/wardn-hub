"""registry namespace metadata

Revision ID: 202607030001
Revises: 202606300002
Create Date: 2026-07-03 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202607030001"
down_revision: str | Sequence[str] | None = "202606300002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table_name in ("mcp_servers", "mcp_server_versions"):
        op.add_column(
            table_name,
            sa.Column(
                "registry_namespace",
                sa.String(length=200),
                server_default="",
                nullable=False,
            ),
        )
        op.add_column(
            table_name,
            sa.Column(
                "registry_namespace_type",
                sa.String(length=32),
                server_default="unknown",
                nullable=False,
            ),
        )
        op.add_column(
            table_name,
            sa.Column(
                "registry_namespace_verification_status",
                sa.String(length=32),
                server_default="unknown",
                nullable=False,
            ),
        )

    op.execute(
        """
        UPDATE mcp_servers
        SET registry_namespace = split_part(name, '/', 1),
            registry_namespace_type = CASE
                WHEN split_part(name, '/', 1) ~ '^io\\.github\\.[^.]+$' THEN 'github'
                WHEN split_part(name, '/', 1) ~ '^[^.]+\\.[^.]+.*$' THEN 'domain'
                ELSE 'unknown'
            END
        WHERE name LIKE '%/%'
        """
    )
    op.execute(
        """
        UPDATE mcp_server_versions
        SET registry_namespace = split_part(name, '/', 1),
            registry_namespace_type = CASE
                WHEN split_part(name, '/', 1) ~ '^io\\.github\\.[^.]+$' THEN 'github'
                WHEN split_part(name, '/', 1) ~ '^[^.]+\\.[^.]+.*$' THEN 'domain'
                ELSE 'unknown'
            END
        WHERE name LIKE '%/%'
        """
    )

    for table_name in ("mcp_servers", "mcp_server_versions"):
        op.create_index(
            op.f(f"ix_{table_name}_registry_namespace"),
            table_name,
            ["registry_namespace"],
            unique=False,
        )
        op.create_index(
            op.f(f"ix_{table_name}_registry_namespace_type"),
            table_name,
            ["registry_namespace_type"],
            unique=False,
        )
        op.create_index(
            op.f(f"ix_{table_name}_registry_namespace_verification_status"),
            table_name,
            ["registry_namespace_verification_status"],
            unique=False,
        )
        op.alter_column(table_name, "registry_namespace", server_default=None)
        op.alter_column(table_name, "registry_namespace_type", server_default=None)
        op.alter_column(
            table_name,
            "registry_namespace_verification_status",
            server_default=None,
        )


def downgrade() -> None:
    for table_name in ("mcp_server_versions", "mcp_servers"):
        op.drop_index(
            op.f(f"ix_{table_name}_registry_namespace_verification_status"),
            table_name=table_name,
        )
        op.drop_index(op.f(f"ix_{table_name}_registry_namespace_type"), table_name=table_name)
        op.drop_index(op.f(f"ix_{table_name}_registry_namespace"), table_name=table_name)
        op.drop_column(table_name, "registry_namespace_verification_status")
        op.drop_column(table_name, "registry_namespace_type")
        op.drop_column(table_name, "registry_namespace")
