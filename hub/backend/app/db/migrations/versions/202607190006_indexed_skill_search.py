"""Add an indexed, content-aware skill search projection.

Revision ID: 202607190006
Revises: 202607190005
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202607190006"
down_revision: str | Sequence[str] | None = "202607190005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "skill_search_documents",
        sa.Column(
            "skill_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skill_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source", sa.String(300), nullable=False),
        sa.Column("source_owner", sa.String(200), nullable=False),
        sa.Column("source_name", sa.String(200), nullable=False),
        sa.Column("install_url", sa.String(2048), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("file_paths", sa.Text(), nullable=False),
        sa.Column("installs", sa.Integer(), nullable=False),
        sa.Column("is_canonical", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("identity_text", sa.Text(), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION wardn_hub_recompute_skill_search_canonical(
            target_source_type text,
            target_source text,
            target_install_url text
        ) RETURNS void
        LANGUAGE plpgsql
        AS $$
        DECLARE
            winner_id uuid;
        BEGIN
            IF target_source_type IS NULL OR target_source IS NULL THEN
                RETURN;
            END IF;

            IF COALESCE(target_install_url, '') = '' THEN
                UPDATE skill_search_documents
                SET is_canonical = true
                WHERE source_type = target_source_type
                  AND source = target_source
                  AND install_url = ''
                  AND is_canonical IS DISTINCT FROM true;
                RETURN;
            END IF;

            SELECT skill_id
            INTO winner_id
            FROM skill_search_documents
            WHERE source_type = target_source_type
              AND source = target_source
              AND install_url = target_install_url
            ORDER BY installs DESC, length(slug), slug, skill_id
            LIMIT 1;

            UPDATE skill_search_documents
            SET is_canonical = (skill_id = winner_id)
            WHERE source_type = target_source_type
              AND source = target_source
              AND install_url = target_install_url
              AND is_canonical IS DISTINCT FROM (skill_id = winner_id);
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION wardn_hub_refresh_skill_search_document(
            target_skill_id uuid
        ) RETURNS void
        LANGUAGE plpgsql
        AS $$
        DECLARE
            previous_source_type text;
            previous_source text;
            previous_install_url text;
            current_source_type text;
            current_source text;
            current_install_url text;
        BEGIN
            SELECT source_type, source, install_url
            INTO previous_source_type, previous_source, previous_install_url
            FROM skill_search_documents
            WHERE skill_id = target_skill_id;

            INSERT INTO skill_search_documents (
                skill_id,
                snapshot_id,
                source_type,
                source,
                source_owner,
                source_name,
                install_url,
                slug,
                name,
                description,
                instructions,
                file_paths,
                installs,
                is_canonical,
                identity_text,
                search_vector,
                updated_at
            )
            SELECT
                skill.id,
                snapshot.id,
                skill.source_type,
                skill.source,
                skill.source_owner,
                skill.source_name,
                skill.install_url,
                skill.slug,
                skill.name,
                skill.description,
                left(snapshot.skill_md, 32768),
                bundle.file_paths,
                skill.installs,
                false,
                lower(
                    skill.source || '/' || skill.slug || ' ' || skill.name || ' ' ||
                    skill.source_owner || ' ' || skill.source_name
                ),
                setweight(
                    to_tsvector(
                        'simple'::regconfig,
                        skill.source || ' ' || skill.slug || ' ' || skill.name || ' ' ||
                        skill.source_owner || ' ' || skill.source_name
                    ),
                    'A'
                ) ||
                setweight(
                    to_tsvector(
                        'english'::regconfig,
                        skill.name || ' ' || skill.description
                    ),
                    'B'
                ) ||
                setweight(
                    to_tsvector(
                        'english'::regconfig,
                        left(snapshot.skill_md, 32768) || ' ' || bundle.file_paths
                    ),
                    'C'
                ),
                now()
            FROM skills AS skill
            JOIN skill_snapshots AS snapshot
              ON snapshot.id = skill.current_snapshot_id
             AND snapshot.skill_id = skill.id
            CROSS JOIN LATERAL (
                SELECT COALESCE(
                    left(string_agg(file->>'path', ' ' ORDER BY file->>'path'), 8192),
                    ''
                ) AS file_paths
                FROM jsonb_array_elements(snapshot.files) AS file
                WHERE jsonb_typeof(file) = 'object'
                  AND file ? 'path'
            ) AS bundle
            WHERE skill.id = target_skill_id
              AND skill.status = 'active'
              AND skill.visibility = 'public'
              AND snapshot.status = 'active'
              AND snapshot.is_latest = true
              AND snapshot.bundle_format_version = 2
              AND snapshot.resolution_status = 'complete'
            ON CONFLICT (skill_id) DO UPDATE
            SET snapshot_id = EXCLUDED.snapshot_id,
                source_type = EXCLUDED.source_type,
                source = EXCLUDED.source,
                source_owner = EXCLUDED.source_owner,
                source_name = EXCLUDED.source_name,
                install_url = EXCLUDED.install_url,
                slug = EXCLUDED.slug,
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                instructions = EXCLUDED.instructions,
                file_paths = EXCLUDED.file_paths,
                installs = EXCLUDED.installs,
                identity_text = EXCLUDED.identity_text,
                search_vector = EXCLUDED.search_vector,
                updated_at = EXCLUDED.updated_at;

            IF NOT FOUND THEN
                DELETE FROM skill_search_documents WHERE skill_id = target_skill_id;
            END IF;

            SELECT source_type, source, install_url
            INTO current_source_type, current_source, current_install_url
            FROM skill_search_documents
            WHERE skill_id = target_skill_id;

            PERFORM wardn_hub_recompute_skill_search_canonical(
                previous_source_type,
                previous_source,
                previous_install_url
            );
            IF (current_source_type, current_source, current_install_url)
                IS DISTINCT FROM
               (previous_source_type, previous_source, previous_install_url) THEN
                PERFORM wardn_hub_recompute_skill_search_canonical(
                    current_source_type,
                    current_source,
                    current_install_url
                );
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION wardn_hub_sync_skill_search_document()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND (
                   NEW.source_type,
                   NEW.source,
                   NEW.source_owner,
                   NEW.source_name,
                   NEW.install_url,
                   NEW.slug,
                   NEW.name,
                   NEW.description,
                   NEW.status,
                   NEW.visibility,
                   NEW.current_snapshot_id
               ) IS NOT DISTINCT FROM (
                   OLD.source_type,
                   OLD.source,
                   OLD.source_owner,
                   OLD.source_name,
                   OLD.install_url,
                   OLD.slug,
                   OLD.name,
                   OLD.description,
                   OLD.status,
                   OLD.visibility,
                   OLD.current_snapshot_id
               ) THEN
                IF NEW.installs IS DISTINCT FROM OLD.installs THEN
                    UPDATE skill_search_documents
                    SET installs = NEW.installs,
                        updated_at = now()
                    WHERE skill_id = NEW.id;
                    PERFORM wardn_hub_recompute_skill_search_canonical(
                        NEW.source_type,
                        NEW.source,
                        NEW.install_url
                    );
                END IF;
                RETURN NEW;
            END IF;

            PERFORM wardn_hub_refresh_skill_search_document(NEW.id);
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION wardn_hub_delete_skill_search_document()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            previous_source_type text;
            previous_source text;
            previous_install_url text;
        BEGIN
            DELETE FROM skill_search_documents
            WHERE skill_id = OLD.id
            RETURNING source_type, source, install_url
            INTO previous_source_type, previous_source, previous_install_url;
            PERFORM wardn_hub_recompute_skill_search_canonical(
                previous_source_type,
                previous_source,
                previous_install_url
            );
            RETURN OLD;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION wardn_hub_sync_snapshot_search_document()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            PERFORM wardn_hub_refresh_skill_search_document(
                CASE WHEN TG_OP = 'DELETE' THEN OLD.skill_id ELSE NEW.skill_id END
            );
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$
        """
    )

    op.execute(
        """
        INSERT INTO skill_search_documents (
            skill_id,
            snapshot_id,
            source_type,
            source,
            source_owner,
            source_name,
            install_url,
            slug,
            name,
            description,
            instructions,
            file_paths,
            installs,
            is_canonical,
            identity_text,
            search_vector,
            updated_at
        )
        SELECT
            skill.id,
            snapshot.id,
            skill.source_type,
            skill.source,
            skill.source_owner,
            skill.source_name,
            skill.install_url,
            skill.slug,
            skill.name,
            skill.description,
            left(snapshot.skill_md, 32768),
            bundle.file_paths,
            skill.installs,
            false,
            lower(
                skill.source || '/' || skill.slug || ' ' || skill.name || ' ' ||
                skill.source_owner || ' ' || skill.source_name
            ),
            setweight(
                to_tsvector(
                    'simple'::regconfig,
                    skill.source || ' ' || skill.slug || ' ' || skill.name || ' ' ||
                    skill.source_owner || ' ' || skill.source_name
                ),
                'A'
            ) ||
            setweight(
                to_tsvector(
                    'english'::regconfig,
                    skill.name || ' ' || skill.description
                ),
                'B'
            ) ||
            setweight(
                to_tsvector(
                    'english'::regconfig,
                    left(snapshot.skill_md, 32768) || ' ' || bundle.file_paths
                ),
                'C'
            ),
            now()
        FROM skills AS skill
        JOIN skill_snapshots AS snapshot
          ON snapshot.id = skill.current_snapshot_id
         AND snapshot.skill_id = skill.id
        CROSS JOIN LATERAL (
            SELECT COALESCE(
                left(string_agg(file->>'path', ' ' ORDER BY file->>'path'), 8192),
                ''
            ) AS file_paths
            FROM jsonb_array_elements(snapshot.files) AS file
            WHERE jsonb_typeof(file) = 'object'
              AND file ? 'path'
        ) AS bundle
        WHERE skill.status = 'active'
          AND skill.visibility = 'public'
          AND snapshot.status = 'active'
          AND snapshot.is_latest = true
          AND snapshot.bundle_format_version = 2
          AND snapshot.resolution_status = 'complete'
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT
                skill_id,
                first_value(skill_id) OVER (
                    PARTITION BY
                        source_type,
                        source,
                        CASE WHEN install_url = '' THEN skill_id::text ELSE install_url END
                    ORDER BY installs DESC, length(slug), slug, skill_id
                ) AS winner_id
            FROM skill_search_documents
        )
        UPDATE skill_search_documents AS document
        SET is_canonical = (document.skill_id = ranked.winner_id)
        FROM ranked
        WHERE ranked.skill_id = document.skill_id
        """
    )

    op.create_index(
        "ix_skill_search_documents_exact_id",
        "skill_search_documents",
        [sa.text("lower(source)"), sa.text("lower(slug)")],
        postgresql_where=sa.text("is_canonical = true"),
    )
    op.create_index(
        "ix_skill_search_documents_owner",
        "skill_search_documents",
        [sa.text("lower(source_owner)")],
        postgresql_where=sa.text("is_canonical = true"),
    )
    op.create_index(
        "ix_skill_search_documents_search_vector",
        "skill_search_documents",
        ["search_vector"],
        postgresql_using="gin",
        postgresql_where=sa.text("is_canonical = true"),
    )
    op.create_index(
        "ix_skill_search_documents_identity_trgm",
        "skill_search_documents",
        ["identity_text"],
        postgresql_using="gin",
        postgresql_ops={"identity_text": "gin_trgm_ops"},
        postgresql_where=sa.text("is_canonical = true"),
    )
    op.create_index(
        "ix_skill_search_documents_canonical_installs",
        "skill_search_documents",
        ["is_canonical", sa.text("installs DESC")],
    )

    op.execute(
        """
        CREATE TRIGGER trg_skills_sync_search_document
        AFTER INSERT OR UPDATE ON skills
        FOR EACH ROW EXECUTE FUNCTION wardn_hub_sync_skill_search_document()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_skills_delete_search_document
        BEFORE DELETE ON skills
        FOR EACH ROW EXECUTE FUNCTION wardn_hub_delete_skill_search_document()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_skill_snapshots_sync_search_document
        AFTER INSERT OR UPDATE OR DELETE ON skill_snapshots
        FOR EACH ROW EXECUTE FUNCTION wardn_hub_sync_snapshot_search_document()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_skill_snapshots_sync_search_document ON skill_snapshots")
    op.execute("DROP TRIGGER IF EXISTS trg_skills_delete_search_document ON skills")
    op.execute("DROP TRIGGER IF EXISTS trg_skills_sync_search_document ON skills")
    op.execute("DROP FUNCTION IF EXISTS wardn_hub_sync_snapshot_search_document()")
    op.execute("DROP FUNCTION IF EXISTS wardn_hub_delete_skill_search_document()")
    op.execute("DROP FUNCTION IF EXISTS wardn_hub_sync_skill_search_document()")
    op.execute("DROP FUNCTION IF EXISTS wardn_hub_refresh_skill_search_document(uuid)")
    op.execute(
        "DROP FUNCTION IF EXISTS wardn_hub_recompute_skill_search_canonical(text, text, text)"
    )
    op.drop_index(
        "ix_skill_search_documents_canonical_installs",
        table_name="skill_search_documents",
    )
    op.drop_index(
        "ix_skill_search_documents_identity_trgm",
        table_name="skill_search_documents",
    )
    op.drop_index(
        "ix_skill_search_documents_search_vector",
        table_name="skill_search_documents",
    )
    op.drop_index("ix_skill_search_documents_owner", table_name="skill_search_documents")
    op.drop_index("ix_skill_search_documents_exact_id", table_name="skill_search_documents")
    op.drop_table("skill_search_documents")
