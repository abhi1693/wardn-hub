import json
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
from app.modules.registry.schemas import RegistryCategoryCreate, RegistryServerVersionCreate


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
            "_meta": {"categories": ["weather"]},
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


def category_model(slug: str = "weather", name: str = "Weather") -> RegistryCategory:
    now = datetime(2026, 6, 23, tzinfo=UTC)
    return RegistryCategory(
        id=uuid4(),
        slug=slug,
        name=name,
        description=f"{name} category",
        sort_order=100,
        status="active",
        created_at=now,
        updated_at=now,
    )


async def categories_by_slug(*args, **kwargs):
    slugs = args[1] if len(args) > 1 else set()
    return {slug: category_model(slug, slug.replace("-", " ").title()) for slug in slugs}


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
        "category": "Search",
        "categories": ["AI Tools"],
        service.PUBLISHER_META_KEY: {
            "category": "Development",
            "categories": ["Cloud Service", "Development"],
        }
    }

    assert service.category_values(payload) == [
        "search",
        "ai-tools",
        "development",
        "cloud-service",
    ]


def test_category_values_extracts_direct_metadata() -> None:
    payload = registry_payload()
    payload.meta = {"categories": ["Weather", "Cloud Service"]}

    assert service.category_values(payload) == ["weather", "cloud-service"]


def test_next_category_sort_order_uses_ten_step_gaps() -> None:
    assert service.next_category_sort_order([]) == 10
    assert service.next_category_sort_order([10, 20, 30]) == 40
    assert service.next_category_sort_order([10, 20, 30], 20) == 40
    assert service.next_category_sort_order([10, 20, 30], 25) == 25


@pytest.mark.asyncio
async def test_create_category_assigns_next_sort_order(monkeypatch) -> None:
    captured_sort_order = None
    now = datetime(2026, 6, 23, tzinfo=UTC)

    async def missing_category(*args, **kwargs):
        return None

    async def sort_orders(*args, **kwargs):
        return [10, 20, 30]

    async def create_category(*args, **kwargs):
        nonlocal captured_sort_order
        captured_sort_order = kwargs["sort_order"]
        return RegistryCategory(
            id=uuid4(),
            slug=kwargs["slug"],
            name=kwargs["name"],
            description=kwargs["description"],
            sort_order=kwargs["sort_order"],
            status="active",
            created_at=now,
            updated_at=now,
        )

    monkeypatch.setattr(service.repository, "get_category_by_slug", missing_category)
    monkeypatch.setattr(service.repository, "list_category_sort_orders", sort_orders)
    monkeypatch.setattr(service.repository, "create_category", create_category)

    response = await service.create_category(
        FakeSession(),
        RegistryCategoryCreate(slug="automation", name="Automation"),
    )

    assert captured_sort_order == 40
    assert response.sort_order == 40


@pytest.mark.asyncio
async def test_create_category_advances_duplicate_requested_sort_order(monkeypatch) -> None:
    now = datetime(2026, 6, 23, tzinfo=UTC)

    async def missing_category(*args, **kwargs):
        return None

    async def sort_orders(*args, **kwargs):
        return [10, 20, 30]

    async def create_category(*args, **kwargs):
        return RegistryCategory(
            id=uuid4(),
            slug=kwargs["slug"],
            name=kwargs["name"],
            description=kwargs["description"],
            sort_order=kwargs["sort_order"],
            status="active",
            created_at=now,
            updated_at=now,
        )

    monkeypatch.setattr(service.repository, "get_category_by_slug", missing_category)
    monkeypatch.setattr(service.repository, "list_category_sort_orders", sort_orders)
    monkeypatch.setattr(service.repository, "create_category", create_category)

    response = await service.create_category(
        FakeSession(),
        RegistryCategoryCreate(slug="automation", name="Automation", sortOrder=20),
    )

    assert response.sort_order == 40


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
    monkeypatch.setattr(service.repository, "list_categories_by_slugs", categories_by_slug)
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
async def test_create_server_version_stores_json_values_on_server(monkeypatch) -> None:
    async def missing_server(*args, **kwargs):
        return None

    async def noop(*args, **kwargs):
        return None

    async def empty_context(*args, **kwargs):
        return {}

    payload = RegistryServerVersionCreate(
        **{
            **registry_payload().model_dump(by_alias=True),
            "repository": {
                "type": "git",
                "source": "github",
                "url": "https://github.com/example/weather",
            },
            "icons": [{"src": "https://example.com/icon.png", "type": "image/png"}],
        }
    )
    session = FakeSession()
    monkeypatch.setattr(service.repository, "get_server", missing_server)
    monkeypatch.setattr(service.repository, "get_server_version", missing_server)
    monkeypatch.setattr(service.repository, "clear_latest_for_server", noop)
    monkeypatch.setattr(service.repository, "sync_server_categories", noop)
    monkeypatch.setattr(service.repository, "list_partner_support_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_by_slugs", categories_by_slug)
    monkeypatch.setattr(service.repository, "list_organizations_by_ids", empty_context)
    monkeypatch.setattr(service.repository, "list_users_by_ids", empty_context)

    await service.create_server_version(session, payload)

    server = next(item for item in session.added if isinstance(item, RegistryServer))
    assert server.repository == {
        "source": "github",
        "type": "git",
        "url": "https://github.com/example/weather",
        "subfolder": "",
        "branch": "",
        "tag": "",
    }
    assert server.icons == [
        {"src": "https://example.com/icon.png", "type": "image/png", "sizes": ""}
    ]
    json.dumps(server.repository)
    json.dumps(server.icons)


@pytest.mark.asyncio
async def test_create_server_version_syncs_declared_categories(monkeypatch) -> None:
    synced_categories: list[str] | None = None

    async def missing_server(*args, **kwargs):
        return None

    async def noop(*args, **kwargs):
        return None

    async def sync_categories(*args):
        nonlocal synced_categories
        synced_categories = args[2]

    async def empty_context(*args, **kwargs):
        return {}

    payload = registry_payload()
    payload.meta = {"categories": ["Weather"]}
    monkeypatch.setattr(service.repository, "get_server", missing_server)
    monkeypatch.setattr(service.repository, "get_server_version", missing_server)
    monkeypatch.setattr(service.repository, "clear_latest_for_server", noop)
    monkeypatch.setattr(service.repository, "sync_server_categories", sync_categories)
    monkeypatch.setattr(service.repository, "list_partner_support_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_by_slugs", categories_by_slug)
    monkeypatch.setattr(service.repository, "list_organizations_by_ids", empty_context)
    monkeypatch.setattr(service.repository, "list_users_by_ids", empty_context)

    await service.create_server_version(FakeSession(), payload)

    assert synced_categories == ["weather"]


@pytest.mark.asyncio
async def test_list_published_servers_returns_full_version_data(monkeypatch) -> None:
    server = server_model()
    server.repository = {
        "type": "git",
        "url": "https://example.com/repo",
        "customRepositoryField": {"nested": True},
    }
    server.icons = [
        {
            "src": "https://example.com/icon.png",
            "customIconField": ["dark", "light"],
        }
    ]
    version = version_model(server.id, "1.0.0", is_latest=True)
    version.packages = [
        {
            "registryType": "npm",
            "identifier": "@example/weather-mcp",
            "version": "1.0.0",
            "transport": {
                "type": "stdio",
                "command": "npx",
                "customTransportField": {"preserve": "transport"},
            },
            "customPackageField": {"preserve": "package"},
        }
    ]
    version.remotes = [
        {
            "type": "streamable-http",
            "url": "https://weather.example.com/mcp",
            "headers": [
                {
                    "name": "Authorization",
                    "value": "Bearer ${TOKEN}",
                    "customHeaderField": "header",
                }
            ],
            "customRemoteField": ["preserve", "remote"],
        }
    ]
    captured: dict[str, int] = {}

    async def published_servers(*args, **kwargs):
        captured.update(kwargs)
        return [(server, version)], 21

    async def published_versions(*args, **kwargs):
        return {server.id: [version]}

    async def empty_context(*args, **kwargs):
        return {}

    monkeypatch.setattr(service.repository, "list_published_servers", published_servers)
    monkeypatch.setattr(
        service.repository,
        "list_published_versions_for_servers",
        published_versions,
    )
    monkeypatch.setattr(service.repository, "list_partner_support_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_by_slugs", categories_by_slug)
    monkeypatch.setattr(service.repository, "list_organizations_by_ids", empty_context)
    monkeypatch.setattr(service.repository, "list_users_by_ids", empty_context)

    response = await service.list_published_servers(FakeSession(), page=2)

    assert captured == {"offset": 20, "limit": 20}
    assert response.metadata.page == 2
    assert response.metadata.per_page == 20
    assert response.metadata.total == 21
    assert response.metadata.pages == 2
    assert response.servers[0].name == server.name
    assert response.servers[0].repository == server.repository
    assert response.servers[0].icons == server.icons
    assert response.servers[0].categories[0].slug == "weather"
    server_payload = response.servers[0].model_dump(by_alias=True)
    assert "server" not in server_payload
    assert "versions" in server_payload
    assert response.servers[0].versions[0].packages == version.packages
    assert response.servers[0].versions[0].remotes == version.remotes
    version_payload = response.servers[0].versions[0].model_dump(by_alias=True)
    assert set(version_payload) == {
        "id",
        "version",
        "packages",
        "remotes",
        "status",
        "statusMessage",
        "isLatest",
        "publishedAt",
        "statusChangedAt",
        "createdAt",
        "updatedAt",
    }
    assert "owner" not in version_payload
    assert "organization" not in version_payload
    assert "categories" not in version_payload
    assert "partnerSupport" not in version_payload
    assert "publishedBy" not in version_payload
    assert "serverId" not in version_payload
    assert "name" not in version_payload
    assert "documentation" not in version_payload
    assert "title" not in version_payload
    assert "description" not in version_payload
    assert "websiteUrl" not in version_payload
    assert "repository" not in version_payload
    assert "icons" not in version_payload
    assert "serverJson" not in version_payload


@pytest.mark.asyncio
async def test_list_published_servers_groups_versions_under_their_server(monkeypatch) -> None:
    weather = server_model()
    calendar = server_model()
    calendar.id = uuid4()
    calendar.name = "io.github.example/calendar"
    calendar.title = "Calendar"
    calendar.description = "Calendar tools"

    weather_v1 = version_model(weather.id, "1.0.0", is_latest=False)
    weather_v2 = version_model(weather.id, "2.0.0", is_latest=True)
    calendar_v1 = version_model(calendar.id, "1.0.0", is_latest=True)
    for version in (weather_v1, weather_v2):
        version.name = weather.name
        version.server_json = {**version.server_json, "name": weather.name}
    calendar_v1.name = calendar.name
    calendar_v1.server_json = {**calendar_v1.server_json, "name": calendar.name}

    async def published_servers(*args, **kwargs):
        return [(weather, weather_v2), (calendar, calendar_v1)], 2

    async def published_versions(*args, **kwargs):
        return {
            weather.id: [weather_v2, weather_v1],
            calendar.id: [calendar_v1],
        }

    async def empty_context(*args, **kwargs):
        return {}

    monkeypatch.setattr(service.repository, "list_published_servers", published_servers)
    monkeypatch.setattr(
        service.repository,
        "list_published_versions_for_servers",
        published_versions,
    )
    monkeypatch.setattr(service.repository, "list_partner_support_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_by_slugs", categories_by_slug)
    monkeypatch.setattr(service.repository, "list_organizations_by_ids", empty_context)
    monkeypatch.setattr(service.repository, "list_users_by_ids", empty_context)

    response = await service.list_published_servers(FakeSession(), page=1)

    versions_by_server = {
        item.name: [version.id for version in item.versions]
        for item in response.servers
    }
    assert versions_by_server == {
        weather.name: [weather_v2.id, weather_v1.id],
        calendar.name: [calendar_v1.id],
    }


@pytest.mark.asyncio
async def test_list_published_servers_uses_legacy_version_category_when_join_missing(
    monkeypatch,
) -> None:
    server = server_model()
    latest = version_model(server.id, "1.0.1", is_latest=True)
    previous = version_model(server.id, "1.0.0", is_latest=False)
    latest.server_json.pop("_meta", None)
    previous.server_json["_meta"] = {
        service.PUBLISHER_META_KEY: {
            "category": "search",
        },
    }

    async def published_servers(*args, **kwargs):
        return [(server, latest)], 1

    async def published_versions(*args, **kwargs):
        return {server.id: [latest, previous]}

    async def empty_context(*args, **kwargs):
        return {}

    monkeypatch.setattr(service.repository, "list_published_servers", published_servers)
    monkeypatch.setattr(
        service.repository,
        "list_published_versions_for_servers",
        published_versions,
    )
    monkeypatch.setattr(service.repository, "list_partner_support_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_by_slugs", categories_by_slug)
    monkeypatch.setattr(service.repository, "list_organizations_by_ids", empty_context)
    monkeypatch.setattr(service.repository, "list_users_by_ids", empty_context)

    response = await service.list_published_servers(FakeSession(), page=1)

    assert response.servers[0].categories[0].slug == "search"
    assert "categories" not in response.servers[0].versions[0].model_dump(by_alias=True)


@pytest.mark.asyncio
async def test_create_server_version_sets_owner_and_actor_metadata(monkeypatch) -> None:
    owner_user_id = uuid4()
    organization_id = uuid4()
    creator_id = uuid4()
    updater_id = uuid4()
    publisher_id = uuid4()

    async def missing_server(*args, **kwargs):
        return None

    async def noop(*args, **kwargs):
        return None

    async def empty_context(*args, **kwargs):
        return {}

    session = FakeSession()
    monkeypatch.setattr(service.repository, "get_server", missing_server)
    monkeypatch.setattr(service.repository, "get_server_version", missing_server)
    monkeypatch.setattr(service.repository, "clear_latest_for_server", noop)
    monkeypatch.setattr(service.repository, "sync_server_categories", noop)
    monkeypatch.setattr(service.repository, "list_partner_support_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_by_slugs", categories_by_slug)
    monkeypatch.setattr(service.repository, "list_organizations_by_ids", empty_context)
    monkeypatch.setattr(service.repository, "list_users_by_ids", empty_context)

    await service.create_server_version(
        session,
        registry_payload(),
        owner_user_id=owner_user_id,
        owner_organization_id=organization_id,
        created_by_user_id=creator_id,
        updated_by_user_id=updater_id,
        publisher_user_id=publisher_id,
    )

    server = next(item for item in session.added if isinstance(item, RegistryServer))
    version = next(item for item in session.added if isinstance(item, RegistryServerVersion))
    assert server.owner_user_id == owner_user_id
    assert server.owner_organization_id == organization_id
    assert server.created_by_user_id == creator_id
    assert server.updated_by_user_id == updater_id
    assert version.owner_user_id == owner_user_id
    assert version.owner_organization_id == organization_id
    assert version.created_by_user_id == creator_id
    assert version.updated_by_user_id == updater_id
    assert version.publisher_user_id == publisher_id


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
async def test_delete_server_deletes_all_versions(monkeypatch) -> None:
    server = server_model()
    server.current_version_id = uuid4()
    latest = version_model(server.id, "2.0.0", is_latest=True)
    previous = version_model(server.id, "1.0.0", is_latest=False)
    synced_categories: list[str] | None = None

    async def get_server(*args, **kwargs):
        return server

    async def list_versions(*args, **kwargs):
        return [latest, previous]

    async def sync_categories(*args):
        nonlocal synced_categories
        synced_categories = args[2]

    monkeypatch.setattr(service.repository, "get_server", get_server)
    monkeypatch.setattr(service.repository, "list_server_versions", list_versions)
    monkeypatch.setattr(service.repository, "sync_server_categories", sync_categories)

    await service.delete_server(FakeSession(), "io.github.example/weather")

    assert server.status == "deleted"
    assert server.current_version_id is None
    assert latest.status == "deleted"
    assert latest.is_latest is False
    assert previous.status == "deleted"
    assert previous.is_latest is False
    assert synced_categories == []


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
