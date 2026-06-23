from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.organizations.models import Organization
from app.modules.partners.models import OrganizationServerSupport
from app.modules.registry import service
from app.modules.registry.category_seed import MCP_SERVERS_CATEGORY_SEEDS
from app.modules.registry.exceptions import (
    DuplicateRegistryVersionError,
    InvalidRegistryCursorError,
    RegistryVersionNotFoundError,
)
from app.modules.registry.models import RegistryCategory, RegistryServer, RegistryServerVersion
from app.modules.registry.schemas import RegistryServerVersionCreate


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = False
        self.refreshed: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushed = True

    async def refresh(self, instance) -> None:
        now = datetime(2026, 6, 23, tzinfo=UTC)
        if getattr(instance, "id", None) is None:
            instance.id = uuid4()
        if getattr(instance, "created_at", None) is None:
            instance.created_at = now
        if getattr(instance, "updated_at", None) is None:
            instance.updated_at = now
        if hasattr(instance, "published_at") and getattr(instance, "published_at", None) is None:
            instance.published_at = now
        if (
            hasattr(instance, "status_changed_at")
            and getattr(instance, "status_changed_at", None) is None
        ):
            instance.status_changed_at = now
        self.refreshed.append(instance)


def registry_payload(version: str = "1.0.0") -> RegistryServerVersionCreate:
    return RegistryServerVersionCreate(
        **{
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "io.github.example/weather",
            "title": "Weather",
            "description": "Weather tools for forecasts",
            "documentation": "# Weather MCP\n\nUse this server for forecast tools.",
            "version": version,
            "packages": [
                {
                    "registryType": "npm",
                    "identifier": "@example/weather-mcp",
                    "version": version,
                    "transport": {"type": "stdio"},
                }
            ],
        }
    )


def server_model() -> RegistryServer:
    now = datetime(2026, 6, 23, tzinfo=UTC)
    return RegistryServer(
        id=uuid4(),
        name="io.github.example/weather",
        title="Weather",
        description="Weather tools for forecasts",
        documentation="# Weather MCP\n\nUse this server for forecast tools.",
        website_url="",
        repository=None,
        icons=[],
        status="active",
        status_message="",
        visibility="public",
        owner_organization_id=None,
        owner_user_id=None,
        created_by_user_id=None,
        updated_by_user_id=None,
        created_at=now,
        updated_at=now,
    )


def version_model(server_id, version: str, *, is_latest: bool) -> RegistryServerVersion:
    now = datetime(2026, 6, 23, tzinfo=UTC)
    payload = registry_payload(version)
    return RegistryServerVersion(
        id=uuid4(),
        server_id=server_id,
        **service.document_values(payload),
        status="active",
        status_message="",
        is_latest=is_latest,
        owner_organization_id=None,
        owner_user_id=None,
        created_by_user_id=None,
        updated_by_user_id=None,
        publisher_user_id=None,
        published_at=now,
        status_changed_at=now,
        created_at=now,
        updated_at=now,
    )


def test_parse_cursor() -> None:
    assert service.parse_cursor(None) == 0
    assert service.parse_cursor("25") == 25

    with pytest.raises(InvalidRegistryCursorError):
        service.parse_cursor("-1")

    with pytest.raises(InvalidRegistryCursorError):
        service.parse_cursor("not-a-cursor")


def test_category_values_extracts_publisher_metadata() -> None:
    payload = registry_payload()
    payload.meta = {
        service.PUBLISHER_META_KEY: {
            "category": "Development",
            "categories": ["Cloud Service", "Development"],
        }
    }

    assert service.category_values(payload) == ["development", "cloud-service"]


def test_seed_categories_match_mcpservers_taxonomy() -> None:
    assert [category.name for category in MCP_SERVERS_CATEGORY_SEEDS] == [
        "Search",
        "Web Scraping",
        "Communication",
        "Productivity",
        "Marketing",
        "Design",
        "Memory",
        "Finance",
        "Development",
        "Database",
        "Cloud Service",
        "File System",
        "Cloud Storage",
        "Version Control",
        "Other",
    ]
    assert len({category.slug for category in MCP_SERVERS_CATEGORY_SEEDS}) == len(
        MCP_SERVERS_CATEGORY_SEEDS
    )


@pytest.mark.asyncio
async def test_seed_default_categories_uses_seed_taxonomy(monkeypatch) -> None:
    captured = None

    async def seed_categories(*args):
        nonlocal captured
        captured = args[1]
        now = datetime(2026, 6, 23, tzinfo=UTC)
        return [
            RegistryCategory(
                id=uuid4(),
                slug=category.slug,
                name=category.name,
                description=category.description,
                sort_order=category.sort_order,
                status="active",
                created_at=now,
                updated_at=now,
            )
            for category in captured
        ]

    monkeypatch.setattr(service.repository, "seed_categories", seed_categories)

    response = await service.seed_default_categories(FakeSession())

    assert captured == MCP_SERVERS_CATEGORY_SEEDS
    assert response.categories[0].slug == "search"
    assert response.categories[-1].slug == "other"


@pytest.mark.asyncio
async def test_create_server_version_creates_server_and_latest(monkeypatch) -> None:
    calls: list[str] = []

    async def missing_server(*args, **kwargs):
        return None

    async def clear_latest(*args, **kwargs):
        calls.append("clear_latest")

    async def sync_categories(*args, **kwargs):
        calls.append("sync_categories")

    async def empty_categories(*args, **kwargs):
        return {}

    monkeypatch.setattr(service.repository, "get_server", missing_server)
    monkeypatch.setattr(service.repository, "get_server_version", missing_server)
    monkeypatch.setattr(service.repository, "clear_latest_for_server", clear_latest)
    monkeypatch.setattr(service.repository, "sync_server_categories", sync_categories)
    monkeypatch.setattr(service.repository, "list_partner_support_for_servers", empty_categories)
    monkeypatch.setattr(service.repository, "list_categories_for_servers", empty_categories)
    monkeypatch.setattr(service.repository, "list_organizations_by_ids", empty_categories)
    monkeypatch.setattr(service.repository, "list_users_by_ids", empty_categories)

    response = await service.create_server_version(FakeSession(), registry_payload())

    assert calls == ["clear_latest", "sync_categories"]
    assert response.server.name == "io.github.example/weather"
    assert response.server.latest_version is not None
    assert response.server.latest_version.version == "1.0.0"
    assert response.version.is_latest is True
    assert response.version.server_json["name"] == "io.github.example/weather"


@pytest.mark.asyncio
async def test_create_server_version_rejects_duplicate(monkeypatch) -> None:
    server = server_model()
    existing = version_model(server.id, "1.0.0", is_latest=True)

    async def existing_version(*args, **kwargs):
        return existing

    monkeypatch.setattr(service.repository, "get_server_version", existing_version)

    with pytest.raises(DuplicateRegistryVersionError):
        await service.create_server_version(FakeSession(), registry_payload())


@pytest.mark.asyncio
async def test_delete_latest_promotes_replacement(monkeypatch) -> None:
    server = server_model()
    latest = version_model(server.id, "2.0.0", is_latest=True)
    replacement = version_model(server.id, "1.0.0", is_latest=False)

    async def get_version(*args, **kwargs):
        return latest

    async def get_server_by_id(*args, **kwargs):
        return server

    async def latest_visible(*args, **kwargs):
        return replacement

    monkeypatch.setattr(service.repository, "get_server_version", get_version)
    monkeypatch.setattr(service.repository, "get_server_by_id", get_server_by_id)
    monkeypatch.setattr(service.repository, "latest_visible_version", latest_visible)

    await service.delete_server_version(FakeSession(), "io.github.example/weather", "2.0.0")

    assert latest.status == "deleted"
    assert latest.is_latest is False
    assert replacement.is_latest is True
    assert server.current_version_id == replacement.id
    assert server.title == replacement.title


@pytest.mark.asyncio
async def test_update_rejects_path_mismatch() -> None:
    with pytest.raises(RegistryVersionNotFoundError):
        await service.update_server_version(
            FakeSession(),
            "io.github.example/weather",
            "1.0.0",
            registry_payload("2.0.0"),
        )


@pytest.mark.asyncio
async def test_get_server_detail_includes_partner_support(monkeypatch) -> None:
    now = datetime(2026, 6, 23, tzinfo=UTC)
    organization = Organization(
        id=uuid4(),
        name="Acme",
        slug="acme",
        status="active",
        is_partner=True,
        partner_status="active",
        partner_tier="official",
        website_url="",
        support_email="support@example.com",
        partner_profile={},
        partner_internal_notes="",
        created_at=now,
        updated_at=now,
    )
    server = server_model()
    server.owner_organization_id = organization.id
    version = version_model(server.id, "1.0.0", is_latest=True)
    version.owner_organization_id = organization.id
    support = OrganizationServerSupport(
        id=uuid4(),
        organization_id=organization.id,
        server_name=server.name,
        support_level="official",
        support_status="active",
        support_url="https://example.com/support",
        docs_url="https://example.com/docs",
        contact_policy={},
        internal_notes="",
        created_at=now,
        updated_at=now,
    )

    async def get_server(*args, **kwargs):
        return server

    async def list_versions(*args, **kwargs):
        return [version]

    async def partner_support(*args, **kwargs):
        return {server.name: [(support, organization)]}

    async def organizations(*args, **kwargs):
        return {organization.id: organization}

    async def users(*args, **kwargs):
        return {}

    async def categories(*args, **kwargs):
        return {
            server.id: [
                RegistryCategory(
                    id=uuid4(),
                    slug="development",
                    name="Development",
                    description="Developer tooling",
                    sort_order=180,
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            ]
        }

    monkeypatch.setattr(service.repository, "get_server", get_server)
    monkeypatch.setattr(service.repository, "list_server_versions", list_versions)
    monkeypatch.setattr(service.repository, "list_partner_support_for_servers", partner_support)
    monkeypatch.setattr(service.repository, "list_categories_for_servers", categories)
    monkeypatch.setattr(service.repository, "list_organizations_by_ids", organizations)
    monkeypatch.setattr(service.repository, "list_users_by_ids", users)

    response = await service.get_server_detail(FakeSession(), server.name)

    assert response.server.owner is not None
    assert response.server.owner.login == "acme"
    assert response.server.partner_support[0].support_level == "official"
    assert response.server.partner_support[0].organization.login == "acme"
    assert response.server.categories[0].slug == "development"
