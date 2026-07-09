"""skills registry

Revision ID: 202607100001
Revises: 202607040001
Create Date: 2026-07-10 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607100001"
down_revision: str | Sequence[str] | None = "202607040001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=300), nullable=False),
        sa.Column("source_owner", sa.String(length=200), nullable=False),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("source_owner_url", sa.String(length=2048), nullable=False),
        sa.Column("source_owner_icon_url", sa.String(length=2048), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("install_url", sa.String(length=2048), nullable=False),
        sa.Column("website_url", sa.String(length=2048), nullable=False),
        sa.Column("repository", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("current_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("installs", sa.Integer(), nullable=False),
        sa.Column("is_duplicate", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "slug", name="uq_skills_source_slug"),
        sa.UniqueConstraint(
            "source_type",
            "source",
            "slug",
            name="uq_skills_source_type_source_slug",
        ),
    )
    op.create_index(op.f("ix_skills_is_duplicate"), "skills", ["is_duplicate"], unique=False)
    op.create_index(op.f("ix_skills_slug"), "skills", ["slug"], unique=False)
    op.create_index(op.f("ix_skills_source"), "skills", ["source"], unique=False)
    op.create_index(op.f("ix_skills_source_name"), "skills", ["source_name"], unique=False)
    op.create_index(op.f("ix_skills_source_owner"), "skills", ["source_owner"], unique=False)
    op.create_index(op.f("ix_skills_status"), "skills", ["status"], unique=False)
    op.create_index(op.f("ix_skills_visibility"), "skills", ["visibility"], unique=False)

    op.create_table(
        "skill_source_owners",
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_owner", sa.String(length=200), nullable=False),
        sa.Column("source_owner_url", sa.String(length=2048), nullable=False),
        sa.Column("source_owner_icon_url", sa.String(length=2048), nullable=False),
        sa.Column("is_official", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_type",
            "source_owner",
            name="uq_skill_source_owners_type_owner",
        ),
    )
    op.create_index(
        op.f("ix_skill_source_owners_is_official"),
        "skill_source_owners",
        ["is_official"],
        unique=False,
    )
    op.create_index(
        op.f("ix_skill_source_owners_source_owner"),
        "skill_source_owners",
        ["source_owner"],
        unique=False,
    )

    op.create_table(
        "skill_snapshots",
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("skill_md", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("files", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_latest", sa.Boolean(), nullable=False),
        sa.Column("publisher_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_id", "content_hash", name="uq_skill_snapshots_skill_hash"),
    )
    op.create_index(
        op.f("ix_skill_snapshots_content_hash"),
        "skill_snapshots",
        ["content_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_skill_snapshots_is_latest"),
        "skill_snapshots",
        ["is_latest"],
        unique=False,
    )
    op.create_index(
        op.f("ix_skill_snapshots_skill_id"),
        "skill_snapshots",
        ["skill_id"],
        unique=False,
    )
    op.create_index(op.f("ix_skill_snapshots_status"), "skill_snapshots", ["status"], unique=False)

    op.create_table(
        "skill_audits",
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("categories", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "audited_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_skill_audits_skill_id"), "skill_audits", ["skill_id"], unique=False)
    op.create_index(op.f("ix_skill_audits_slug"), "skill_audits", ["slug"], unique=False)
    op.create_index(op.f("ix_skill_audits_status"), "skill_audits", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_skill_source_owners_source_owner"), table_name="skill_source_owners")
    op.drop_index(op.f("ix_skill_source_owners_is_official"), table_name="skill_source_owners")
    op.drop_table("skill_source_owners")
    op.drop_index(op.f("ix_skill_audits_status"), table_name="skill_audits")
    op.drop_index(op.f("ix_skill_audits_slug"), table_name="skill_audits")
    op.drop_index(op.f("ix_skill_audits_skill_id"), table_name="skill_audits")
    op.drop_table("skill_audits")
    op.drop_index(op.f("ix_skill_snapshots_status"), table_name="skill_snapshots")
    op.drop_index(op.f("ix_skill_snapshots_skill_id"), table_name="skill_snapshots")
    op.drop_index(op.f("ix_skill_snapshots_is_latest"), table_name="skill_snapshots")
    op.drop_index(op.f("ix_skill_snapshots_content_hash"), table_name="skill_snapshots")
    op.drop_table("skill_snapshots")
    op.drop_index(op.f("ix_skills_visibility"), table_name="skills")
    op.drop_index(op.f("ix_skills_status"), table_name="skills")
    op.drop_index(op.f("ix_skills_source_owner"), table_name="skills")
    op.drop_index(op.f("ix_skills_source_name"), table_name="skills")
    op.drop_index(op.f("ix_skills_source"), table_name="skills")
    op.drop_index(op.f("ix_skills_slug"), table_name="skills")
    op.drop_index(op.f("ix_skills_is_duplicate"), table_name="skills")
    op.drop_table("skills")
