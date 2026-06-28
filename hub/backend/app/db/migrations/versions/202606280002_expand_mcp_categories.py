"""expand mcp categories

Revision ID: 202606280002
Revises: 202606280001
Create Date: 2026-06-28 00:00:00.000000

"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "202606280002"
down_revision: str | Sequence[str] | None = "202606280001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CATEGORIES = [
    ("aggregators", "Aggregators", "Multi-source aggregation and gateway MCP servers.", 100),
    (
        "art-culture",
        "Art & Culture",
        "Art, culture, creative collections, and media archive MCP servers.",
        110,
    ),
    (
        "architecture-design",
        "Architecture & Design",
        "Architecture, design systems, CAD, and spatial design MCP servers.",
        120,
    ),
    (
        "browser-automation",
        "Browser Automation",
        "Browser control, web automation, scraping, and extraction MCP servers.",
        130,
    ),
    (
        "biology-medicine-bioinformatics",
        "Biology Medicine and Bioinformatics",
        "Healthcare, biology, medicine, and bioinformatics MCP servers.",
        140,
    ),
    (
        "cloud-platforms",
        "Cloud Platforms",
        "Cloud provider, infrastructure, and platform operation MCP servers.",
        150,
    ),
    ("code-execution", "Code Execution", "Sandboxed code execution and runtime MCP servers.", 160),
    (
        "coding-agents",
        "Coding Agents",
        "Agentic coding, code review, and engineering-assistant MCP servers.",
        170,
    ),
    (
        "command-line",
        "Command Line",
        "Terminal, shell, and command-line workflow MCP servers.",
        180,
    ),
    (
        "communication",
        "Communication",
        "Messaging, meetings, email, and collaboration MCP servers.",
        190,
    ),
    (
        "conversational-ai",
        "Conversational AI",
        "Chat, voice assistant, and conversational AI MCP servers.",
        200,
    ),
    (
        "cryptography",
        "Cryptography",
        "Cryptography, keys, signing, and secure identity MCP servers.",
        210,
    ),
    (
        "customer-data-platforms",
        "Customer Data Platforms",
        "Customer profiles, CRM data, analytics identity, and CDP MCP servers.",
        220,
    ),
    ("databases", "Databases", "Database, SQL, NoSQL, vector store, and query MCP servers.", 230),
    (
        "data-platforms",
        "Data Platforms",
        "Warehouses, lakes, ETL, and business data platform MCP servers.",
        240,
    ),
    (
        "delivery",
        "Delivery",
        "Shipping, logistics, dispatch, and delivery operation MCP servers.",
        250,
    ),
    (
        "developer-tools",
        "Developer Tools",
        "Developer productivity, build, test, and utility MCP servers.",
        260,
    ),
    (
        "data-science-tools",
        "Data Science Tools",
        "Notebook, statistics, ML, and data science workflow MCP servers.",
        270,
    ),
    (
        "data-visualization",
        "Data Visualization",
        "Charting, dashboard, and visualization MCP servers.",
        280,
    ),
    (
        "embedded-system",
        "Embedded system",
        "Embedded systems, hardware, firmware, and IoT MCP servers.",
        290,
    ),
    ("education", "Education", "Learning, teaching, academic, and education MCP servers.", 300),
    ("e-commerce", "E-Commerce", "Commerce, catalog, orders, and marketplace MCP servers.", 310),
    (
        "environment-nature",
        "Environment & Nature",
        "Environment, nature, climate, and sustainability MCP servers.",
        320,
    ),
    (
        "file-systems",
        "File Systems",
        "Local, remote, object, and document file system MCP servers.",
        330,
    ),
    (
        "finance-fintech",
        "Finance & Fintech",
        "Financial data, fintech, accounting, and crypto MCP servers.",
        340,
    ),
    ("gaming", "Gaming", "Games, game services, and interactive entertainment MCP servers.", 350),
    (
        "home-automation",
        "Home Automation",
        "Smart home, home services, and automation MCP servers.",
        360,
    ),
    (
        "knowledge-memory",
        "Knowledge & Memory",
        "Memory, context, notes, and knowledge management MCP servers.",
        370,
    ),
    (
        "legal",
        "Legal",
        "Legal research, contracts, compliance, and case workflow MCP servers.",
        380,
    ),
    (
        "location-services",
        "Location Services",
        "Maps, geocoding, routing, and location intelligence MCP servers.",
        390,
    ),
    ("marketing", "Marketing", "Marketing, sales, growth, and brand operation MCP servers.", 400),
    (
        "monitoring",
        "Monitoring",
        "Monitoring, observability, alerting, and telemetry MCP servers.",
        410,
    ),
    (
        "multimedia-process",
        "Multimedia Process",
        "Image, audio, video, and media processing MCP servers.",
        420,
    ),
    (
        "os-automation",
        "OS Automation",
        "Desktop, operating system, and local automation MCP servers.",
        430,
    ),
    (
        "product-management",
        "Product Management",
        "Product, project, roadmap, and task management MCP servers.",
        440,
    ),
    ("real-estate", "Real Estate", "Real estate, property, and home service MCP servers.", 450),
    ("research", "Research", "Science, research, papers, and scholarly workflow MCP servers.", 460),
    (
        "search-data-extraction",
        "Search & Data Extraction",
        "Search, retrieval, crawling, and data extraction MCP servers.",
        470,
    ),
    ("security", "Security", "Security, vulnerability, audit, and identity MCP servers.", 480),
    (
        "social-media",
        "Social Media",
        "Social media, content platform, and community MCP servers.",
        490,
    ),
    (
        "spirituality-esoterica",
        "Spirituality & Esoterica",
        "Spirituality, astrology, esoterica, and reflective MCP servers.",
        500,
    ),
    ("sports", "Sports", "Sports data, teams, schedules, and performance MCP servers.", 510),
    (
        "support-service-management",
        "Support & Service Management",
        "Support desk, ITSM, service management, and customer service MCP servers.",
        520,
    ),
    (
        "translation-services",
        "Translation Services",
        "Translation, localization, and multilingual workflow MCP servers.",
        530,
    ),
    ("text-to-speech", "Text-to-Speech", "Speech synthesis and audio generation MCP servers.", 540),
    (
        "speech-to-text",
        "Speech-to-Text",
        "Transcription, speech recognition, and voice input MCP servers.",
        550,
    ),
    (
        "travel-transportation",
        "Travel & Transportation",
        "Travel, transit, mobility, and transportation MCP servers.",
        560,
    ),
    (
        "version-control",
        "Version Control",
        "Repository, issue, pull request, and source control MCP servers.",
        570,
    ),
    (
        "workplace-productivity",
        "Workplace & Productivity",
        "Workplace, documents, calendar, and productivity MCP servers.",
        580,
    ),
    (
        "other-tools-integrations",
        "Other Tools and Integrations",
        "Tools and integrations that do not fit an existing primary category.",
        1000,
    ),
]

CATEGORY_BY_SLUG = {
    slug: {
        "slug": slug,
        "name": name,
        "description": description,
        "sort_order": sort_order,
    }
    for slug, name, description, sort_order in CATEGORIES
}

LEGACY_SLUG_RENAMES = {
    "search": "search-data-extraction",
    "web-scraping": "browser-automation",
    "productivity": "workplace-productivity",
    "design": "architecture-design",
    "memory": "knowledge-memory",
    "finance": "finance-fintech",
    "development": "developer-tools",
    "database": "databases",
    "cloud-service": "cloud-platforms",
    "file-system": "file-systems",
    "cloud-storage": "file-systems",
    "other": "other-tools-integrations",
}


def upgrade() -> None:
    bind = op.get_bind()

    for old_slug, new_slug in LEGACY_SLUG_RENAMES.items():
        category = CATEGORY_BY_SLUG[new_slug]
        old_row = (
            bind.execute(
                sa.text("SELECT id FROM mcp_categories WHERE slug = :slug"),
                {"slug": old_slug},
            )
            .mappings()
            .first()
        )
        if old_row is None:
            continue

        target_row = (
            bind.execute(
                sa.text("SELECT id FROM mcp_categories WHERE slug = :slug"),
                {"slug": new_slug},
            )
            .mappings()
            .first()
        )
        if target_row is None:
            bind.execute(
                sa.text(
                    """
                    UPDATE mcp_categories
                    SET slug = :slug,
                        name = :name,
                        description = :description,
                        sort_order = :sort_order,
                        updated_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": old_row["id"], **category},
            )
            continue

        if target_row["id"] == old_row["id"]:
            continue

        links_to_move = (
            bind.execute(
                sa.text(
                    """
                    SELECT old_link.server_id, old_link.source
                    FROM mcp_server_categories old_link
                    WHERE old_link.category_id = :old_id
                      AND NOT EXISTS (
                          SELECT 1
                          FROM mcp_server_categories target_link
                          WHERE target_link.server_id = old_link.server_id
                            AND target_link.category_id = :target_id
                      )
                    """
                ),
                {"old_id": old_row["id"], "target_id": target_row["id"]},
            )
            .mappings()
            .all()
        )
        for link in links_to_move:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO mcp_server_categories (id, server_id, category_id, source)
                    VALUES (:id, :server_id, :category_id, :source)
                    """
                ),
                {
                    "id": uuid4(),
                    "server_id": link["server_id"],
                    "category_id": target_row["id"],
                    "source": link["source"],
                },
            )
        bind.execute(
            sa.text("DELETE FROM mcp_server_categories WHERE category_id = :old_id"),
            {"old_id": old_row["id"]},
        )
        bind.execute(
            sa.text("DELETE FROM mcp_categories WHERE id = :old_id"),
            {"old_id": old_row["id"]},
        )

    bind.execute(
        sa.text(
            """
            INSERT INTO mcp_categories (id, slug, name, description, sort_order, status)
            VALUES (:id, :slug, :name, :description, :sort_order, 'active')
            ON CONFLICT (slug) DO UPDATE
            SET name = EXCLUDED.name,
                description = EXCLUDED.description,
                sort_order = EXCLUDED.sort_order,
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
