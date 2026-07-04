import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.events.models import EventRecord
from app.modules.organizations.models import Organization
from app.modules.partners.models import OrganizationServerSupport
from app.modules.registry import service
from app.modules.registry.category_seed import MCP_SERVERS_CATEGORY_SEEDS
from app.modules.registry.exceptions import (
    DuplicateRegistryVersionError,
    InvalidRegistryCursorError,
    InvalidRegistryVersionError,
    RegistryAccessDeniedError,
    RegistryOwnershipClaimError,
    RegistryServerNotFoundError,
    RegistryVersionNotFoundError,
)
from app.modules.registry.models import RegistryCategory, RegistryServer, RegistryServerVersion
from app.modules.registry.schemas import (
    RegistryCategoryCreate,
    RegistryListMetadata,
    RegistryServerListResponse,
    RegistryServerVersionCreate,
)
from app.modules.users.models import User


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


def test_document_values_derives_registry_namespace_metadata() -> None:
    payload = registry_payload()

    values = service.document_values(payload)

    assert values["registry_namespace"] == "io.github.example"
    assert values["registry_namespace_type"] == "github"
    assert values["registry_namespace_verification_status"] == "unknown"


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


def test_actor_summary_uses_user_display_name_when_profile_names_are_blank() -> None:
    user = User(id=uuid4(), email="publisher@example.com", first_name="", last_name="")

    actor = service.actor_summary_for_user(user)

    assert actor.name == "publisher@example.com"
    assert actor.login == "publisher@example.com"


def test_parse_cursor() -> None:
    assert service.parse_cursor(None) == 0
    assert service.parse_cursor("25") == 25

    with pytest.raises(InvalidRegistryCursorError):
        service.parse_cursor("-1")

    with pytest.raises(InvalidRegistryCursorError):
        service.parse_cursor("not-a-cursor")


def test_version_summary_normalizes_stored_remote_query_parameters() -> None:
    version = version_model(uuid4(), "1.0.0", is_latest=True)
    version.remotes = [
        {
            "url": "https://mcp.browserbase.com/mcp?browserbaseApiKey={browserbaseApiKey}",
            "type": "streamable-http",
            "authentication": {
                "type": "query",
                "queryParameters": [
                    {
                        "name": "browserbaseApiKey",
                        "value": "",
                        "secret": True,
                        "required": True,
                    }
                ],
            },
        }
    ]

    response = service.version_summary(version)

    assert response.remotes == [
        {
            "url": "https://mcp.browserbase.com/mcp",
            "type": "streamable-http",
            "authentication": {"type": "query"},
            "queryParameters": [
                {
                    "name": "browserbaseApiKey",
                    "value": "",
                    "isSecret": True,
                    "isRequired": True,
                }
            ],
        }
    ]


def test_registry_tools_from_server_json_extracts_mcp_tool_metadata() -> None:
    tools = service.registry_tools_from_server_json(
        {
            "name": "io.github.example/weather",
            "_meta": {
                "introspection": {
                    "tools/list": {
                        "result": {
                            "tools": [
                                {
                                    "name": "get_forecast",
                                    "title": "Get forecast",
                                    "description": "Get a weather forecast.",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "location": {
                                                "type": "string",
                                                "description": "City or ZIP code.",
                                            },
                                            "days": {"type": "integer"},
                                        },
                                        "required": ["location"],
                                    },
                                    "outputSchema": {"type": "object"},
                                    "annotations": {"readOnlyHint": True},
                                    "icons": [
                                        {
                                            "src": "https://example.com/weather.png",
                                            "mimeType": "image/png",
                                        }
                                    ],
                                    "execution": {"taskSupport": "optional"},
                                }
                            ]
                        }
                    }
                }
            },
        }
    )

    assert len(tools) == 1
    assert tools[0].name == "get_forecast"
    assert tools[0].title == "Get forecast"
    assert tools[0].annotations == {"readOnlyHint": True}
    assert tools[0].icons == [
        {"src": "https://example.com/weather.png", "mimeType": "image/png"}
    ]
    assert tools[0].execution == {"taskSupport": "optional"}
    assert tools[0].input_schema["type"] == "object"
    assert tools[0].output_schema["type"] == "object"
    assert tools[0].parameters[0].name == "location"
    assert tools[0].parameters[0].type_ == "string"
    assert tools[0].parameters[0].required is True
    assert tools[0].parameters[1].name == "days"
    assert tools[0].parameters[1].type_ == "integer"
    assert tools[0].parameters[1].required is False


def test_registry_prompts_from_server_json_extracts_mcp_prompt_metadata() -> None:
    prompts = service.registry_prompts_from_server_json(
        {
            "name": "io.github.example/weather",
            "_meta": {
                "introspection": {
                    "prompts/list": {
                        "result": {
                            "prompts": [
                                {
                                    "name": "daily_briefing",
                                    "title": "Daily briefing",
                                    "description": "Create a weather briefing.",
                                    "arguments": [
                                        {
                                            "name": "location",
                                            "description": "City or ZIP code.",
                                            "required": True,
                                        }
                                    ],
                                    "icons": [{"src": "https://example.com/weather.svg"}],
                                }
                            ]
                        }
                    }
                }
            },
        }
    )

    assert len(prompts) == 1
    assert prompts[0].name == "daily_briefing"
    assert prompts[0].title == "Daily briefing"
    assert prompts[0].description == "Create a weather briefing."
    assert prompts[0].arguments[0].name == "location"
    assert prompts[0].arguments[0].description == "City or ZIP code."
    assert prompts[0].arguments[0].required is True
    assert prompts[0].icons == [{"src": "https://example.com/weather.svg"}]


def test_registry_resources_from_server_json_extracts_mcp_resource_metadata() -> None:
    server_json = {
        "name": "io.github.example/weather",
        "_meta": {
            "introspection": {
                "resources/list": {
                    "result": {
                        "resources": [
                            {
                                "uri": "file:///project/README.md",
                                "name": "README.md",
                                "title": "Project documentation",
                                "description": "Primary docs.",
                                "mimeType": "text/markdown",
                                "size": 2048,
                                "annotations": {"audience": ["user"], "priority": 0.8},
                                "icons": [{"src": "https://example.com/readme.svg"}],
                            }
                        ]
                    }
                },
                "resources/templates/list": {
                    "result": {
                        "resourceTemplates": [
                            {
                                "uriTemplate": "file:///{path}",
                                "name": "Project files",
                                "description": "Read project files.",
                                "mimeType": "application/octet-stream",
                            }
                        ]
                    }
                },
            }
        },
    }

    resources = service.registry_resources_from_server_json(server_json)
    templates = service.registry_resource_templates_from_server_json(server_json)

    assert len(resources) == 1
    assert resources[0].uri == "file:///project/README.md"
    assert resources[0].name == "README.md"
    assert resources[0].title == "Project documentation"
    assert resources[0].description == "Primary docs."
    assert resources[0].mime_type == "text/markdown"
    assert resources[0].size == 2048
    assert resources[0].annotations == {"audience": ["user"], "priority": 0.8}
    assert resources[0].icons == [{"src": "https://example.com/readme.svg"}]
    assert len(templates) == 1
    assert templates[0].uri_template == "file:///{path}"
    assert templates[0].name == "Project files"
    assert templates[0].mime_type == "application/octet-stream"


def test_trust_report_explains_quality_score_components() -> None:
    version = version_model(uuid4(), "1.0.0", is_latest=True)
    version.quality_score = 96
    version.documentation = (
        "## Installation\nRun npx.\n\n"
        "## Configuration\nSet WEATHER_API_TOKEN.\n\n"
        "## Capabilities\nProvides forecast tools."
    )
    version.packages = [
        {
            "registryType": "npm",
            "identifier": "@example/weather-mcp",
            "transport": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@example/weather-mcp"],
                "env": {"WEATHER_API_TOKEN": ""},
            },
            "environmentVariables": [
                {
                    "name": "WEATHER_API_TOKEN",
                    "description": "Weather API token.",
                    "isRequired": True,
                    "isSecret": True,
                }
            ],
        }
    ]
    version.server_json = {
        **version.server_json,
        "documentation": version.documentation,
        "license": "MIT",
        "packages": version.packages,
        "_meta": {
            "categories": ["weather"],
            "maintenance": {"lastCommitAt": "2026-06-01T00:00:00Z"},
            "securityReview": {"status": "reviewed"},
            "sourceReview": {
                "human": {
                    "filesRead": ["README.md"],
                    "installCommands": ["npx -y @example/weather-mcp"],
                    "commandArguments": ["-y @example/weather-mcp"],
                    "capabilitiesReviewed": True,
                    "limitationsReviewed": True,
                    "unknowns": [],
                }
            },
        },
    }

    report = service.trust_report_for_version(version)

    assert report.overall_score == 96
    assert report.score_source == "manual"
    assert {component.key for component in report.components} == {
        "schemaCompleteness",
        "documentation",
        "sourceReview",
        "targetMetadata",
        "license",
        "maintenance",
        "registryNamespace",
        "ownerVerification",
        "securityReview",
    }
    assert report.components[0].evidence


def test_project_list_response_fields_keeps_only_requested_server_fields() -> None:
    server = server_model()
    version = version_model(server.id, "1.0.0", is_latest=True)
    response = RegistryServerListResponse(
        servers=[service.server_summary(server, version)],
        metadata=RegistryListMetadata(count=1, nextCursor=""),
    )

    projected = service.project_list_response_fields(
        response,
        fields="id,name,title,description,icons,categories,latestVersion",
    )

    assert projected == {
        "servers": [
            {
                "id": server.id,
                "name": server.name,
                "title": server.title,
                "description": server.description,
                "icons": server.icons,
                "categories": [],
                "latestVersion": {
                    "id": version.id,
                    "version": version.version,
                    "status": version.status,
                    "qualityScore": None,
                    "trustReport": service.trust_report_for_version(version).model_dump(
                        by_alias=True
                    ),
                    "publishedAt": version.published_at,
                    "publishedBy": None,
                },
            }
        ],
        "metadata": {"count": 1, "nextCursor": ""},
    }
    server_payload = projected["servers"][0]
    assert "documentation" not in server_payload
    assert "versions" not in server_payload
    assert "packages" not in server_payload
    assert "remotes" not in server_payload
    assert "owner" not in server_payload
    assert "partnerSupport" not in server_payload


def test_project_list_response_fields_rejects_unknown_fields() -> None:
    response = RegistryServerListResponse(
        servers=[],
        metadata=RegistryListMetadata(count=0, nextCursor=""),
    )

    with pytest.raises(ValueError, match="unknown response field"):
        service.project_list_response_fields(response, fields="id,unknown")

    with pytest.raises(ValueError, match="unknown response field"):
        service.project_list_response_fields(response, fields="versions")


def test_category_values_extracts_publisher_metadata() -> None:
    payload = registry_payload()
    payload.meta = {
        "category": "Search",
        "categories": ["AI Tools"],
        service.PUBLISHER_META_KEY: {
            "category": "Development",
            "categories": ["Cloud Service", "Development"],
        },
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
    assert [category.slug for category in MCP_SERVERS_CATEGORY_SEEDS[:4]] == [
        "aggregators",
        "art-culture",
        "architecture-design",
        "browser-automation",
    ]
    assert [category.slug for category in MCP_SERVERS_CATEGORY_SEEDS[-4:]] == [
        "travel-transportation",
        "version-control",
        "workplace-productivity",
        "other-tools-integrations",
    ]
    assert len(MCP_SERVERS_CATEGORY_SEEDS) == 50
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
    assert response.categories[0].slug == "aggregators"
    assert response.categories[-1].slug == "other-tools-integrations"


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

    session = FakeSession()
    response = await service.create_server_version(session, registry_payload())

    assert calls == ["clear_latest", "sync_categories"]
    assert response.server.name == "io.github.example/weather"
    assert response.server.latest_version is not None
    assert response.server.latest_version.version == "1.0.0"
    assert response.version.is_latest is True
    assert response.version.server_json["name"] == "io.github.example/weather"
    event_types = [item.event_type for item in session.added if isinstance(item, EventRecord)]
    assert event_types == ["registry.server.published", "registry.version.published"]


@pytest.mark.asyncio
async def test_create_server_version_rejects_new_server_after_initial_version(
    monkeypatch,
) -> None:
    async def missing_server(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_server", missing_server)
    monkeypatch.setattr(service.repository, "get_server_version", missing_server)

    with pytest.raises(
        InvalidRegistryVersionError,
        match="new servers must start at Wardn registry version 1.0.0",
    ):
        await service.create_server_version(FakeSession(), registry_payload("1.5.0"))


@pytest.mark.asyncio
async def test_create_existing_server_version_emits_version_event_only(monkeypatch) -> None:
    server = server_model()

    async def get_server(*args, **kwargs):
        return server

    async def missing_version(*args, **kwargs):
        return None

    async def noop(*args, **kwargs):
        return None

    async def empty_context(*args, **kwargs):
        return {}

    monkeypatch.setattr(service.repository, "get_server", get_server)
    monkeypatch.setattr(service.repository, "get_server_version", missing_version)
    monkeypatch.setattr(service.repository, "clear_latest_for_server", noop)
    monkeypatch.setattr(service.repository, "sync_server_categories", noop)
    monkeypatch.setattr(service.repository, "list_partner_support_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_by_slugs", categories_by_slug)
    monkeypatch.setattr(service.repository, "list_organizations_by_ids", empty_context)
    monkeypatch.setattr(service.repository, "list_users_by_ids", empty_context)
    session = FakeSession()

    await service.create_server_version(session, registry_payload("2.0.0"))

    event_types = [item.event_type for item in session.added if isinstance(item, EventRecord)]
    assert event_types == ["registry.version.published"]


@pytest.mark.asyncio
async def test_update_version_quality_score_sets_score(monkeypatch) -> None:
    server = server_model()
    version = version_model(server.id, "1.0.0", is_latest=True)
    server.current_version_id = version.id

    async def get_version(*args, **kwargs):
        return version

    async def get_server_by_id(*args, **kwargs):
        return server

    async def empty_context(*args, **kwargs):
        return {}

    monkeypatch.setattr(service.repository, "get_server_version", get_version)
    monkeypatch.setattr(service.repository, "get_server_by_id", get_server_by_id)
    monkeypatch.setattr(service.repository, "list_partner_support_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_by_slugs", categories_by_slug)
    monkeypatch.setattr(service.repository, "list_organizations_by_ids", empty_context)
    monkeypatch.setattr(service.repository, "list_users_by_ids", empty_context)

    response = await service.update_version_quality_score(
        FakeSession(),
        server.name,
        version.version,
        96,
        trust_report=service.RegistryTrustReport(
            overallScore=96,
            scoreSource="manual",
            status="passed",
            summary="Scorer report.",
            components=[
                {
                    "key": "documentation",
                    "label": "Documentation",
                    "score": 90,
                    "status": "passed",
                    "summary": "Documentation is strong.",
                    "evidence": ["docs.setup passed."],
                }
            ],
        ),
    )

    assert version.quality_score == 96
    assert version.server_json["_meta"]["wardnTrustReport"]["overallScore"] == 96
    assert response.version.quality_score == 96
    assert response.version.trust_report is not None
    assert response.version.trust_report.summary == "Scorer report."
    assert response.server.quality_score == 96
    assert response.server.latest_version is not None
    assert response.server.latest_version.quality_score == 96


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
        "qualityScore",
        "trustReport",
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
        item.name: [version.id for version in item.versions] for item in response.servers
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
async def test_claim_server_ownership_with_wardn_json_sets_verified_owner(monkeypatch) -> None:
    owner_user_id = uuid4()
    server = server_model()
    server.repository = {"source": "github", "url": "example/weather-mcp"}
    latest = version_model(server.id, "1.0.0", is_latest=True)
    latest.repository = {"source": "github", "url": "https://github.com/example/weather-mcp"}
    current_user = User(
        id=owner_user_id,
        email="owner@example.com",
        first_name="Owner",
        last_name="User",
        is_active=True,
    )

    async def get_server(*args, **kwargs):
        return server

    async def list_versions(*args, **kwargs):
        return [latest]

    async def manifest(*args, **kwargs):
        return service.WardnOwnershipManifest(
            payload={"servers": {server.name: {"owners": [{"userId": str(owner_user_id)}]}}},
            source_url="https://raw.githubusercontent.com/example/weather-mcp/main/wardn.json",
        )

    async def empty_context(*args, **kwargs):
        return {}

    async def users_by_id(*args, **kwargs):
        return {owner_user_id: current_user}

    session = FakeSession()
    monkeypatch.setattr(service.repository, "get_published_server", get_server)
    monkeypatch.setattr(service.repository, "list_published_server_versions", list_versions)
    monkeypatch.setattr(service, "fetch_wardn_ownership_manifest", manifest)
    monkeypatch.setattr(service.repository, "list_partner_support_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_by_slugs", categories_by_slug)
    monkeypatch.setattr(service.repository, "list_organizations_by_ids", empty_context)
    monkeypatch.setattr(service.repository, "list_users_by_ids", users_by_id)

    response = await service.claim_server_ownership(session, server.name, current_user)

    assert session.flushed is True
    assert server.owner_user_id == owner_user_id
    assert latest.owner_user_id == owner_user_id
    assert response.verified is True
    assert response.server.owner is not None
    assert response.server.owner.id == owner_user_id
    ownership = latest.server_json["_meta"]["wardnOwnership"]
    assert ownership["verified"] is True
    assert ownership["userId"] == str(owner_user_id)
    report = response.server.trust_report
    assert report is not None
    owner_component = next(
        component for component in report.components if component.key == "ownerVerification"
    )
    assert owner_component.score == 100


@pytest.mark.asyncio
async def test_claim_server_ownership_with_website_root_wardn_json(monkeypatch) -> None:
    owner_user_id = uuid4()
    server = server_model()
    server.website_url = "https://weather.example/docs"
    latest = version_model(server.id, "1.0.0", is_latest=True)
    latest.repository = None
    latest.website_url = "https://weather.example/mcp"
    current_user = User(
        id=owner_user_id,
        email="owner@example.com",
        first_name="Owner",
        last_name="User",
        is_active=True,
    )

    async def get_server(*args, **kwargs):
        return server

    async def list_versions(*args, **kwargs):
        return [latest]

    async def manifest(website_url, *args, **kwargs):
        assert website_url == latest.website_url
        return service.WardnOwnershipManifest(
            payload={"servers": {server.name: {"owners": [{"userId": str(owner_user_id)}]}}},
            source_url="https://weather.example/wardn.json",
        )

    async def empty_context(*args, **kwargs):
        return {}

    async def users_by_id(*args, **kwargs):
        return {owner_user_id: current_user}

    session = FakeSession()
    monkeypatch.setattr(service.repository, "get_published_server", get_server)
    monkeypatch.setattr(service.repository, "list_published_server_versions", list_versions)
    monkeypatch.setattr(service, "fetch_wardn_ownership_manifest_from_website", manifest)
    monkeypatch.setattr(service.repository, "list_partner_support_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_by_slugs", categories_by_slug)
    monkeypatch.setattr(service.repository, "list_organizations_by_ids", empty_context)
    monkeypatch.setattr(service.repository, "list_users_by_ids", users_by_id)

    response = await service.claim_server_ownership(session, server.name, current_user)

    assert session.flushed is True
    assert server.owner_user_id == owner_user_id
    assert latest.owner_user_id == owner_user_id
    ownership = latest.server_json["_meta"]["wardnOwnership"]
    assert ownership["source"] == "https://weather.example/wardn.json"
    assert response.verification_source == "https://weather.example/wardn.json"


@pytest.mark.asyncio
async def test_website_wardn_json_rejects_private_initial_host() -> None:
    with pytest.raises(RegistryOwnershipClaimError, match="public address"):
        await service.fetch_wardn_ownership_manifest_from_website("http://127.0.0.1:8000")


@pytest.mark.asyncio
async def test_website_wardn_json_rejects_private_redirect_target(monkeypatch) -> None:
    requested_urls: list[str] = []

    class RedirectResponse:
        status_code = 302
        headers = {"location": "http://127.0.0.1:8000/wardn.json"}
        url = "http://93.184.216.34/wardn.json"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, *args, **kwargs):
            requested_urls.append(url)
            return RedirectResponse()

    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)

    with pytest.raises(RegistryOwnershipClaimError, match="public address"):
        await service.fetch_wardn_ownership_manifest_from_website("http://93.184.216.34")

    assert requested_urls == ["http://93.184.216.34/wardn.json"]


@pytest.mark.asyncio
async def test_claim_server_ownership_rejects_missing_user_uuid(monkeypatch) -> None:
    current_user = User(
        id=uuid4(),
        email="owner@example.com",
        first_name="Owner",
        last_name="User",
        is_active=True,
    )
    server = server_model()
    server.repository = {"source": "github", "url": "example/weather-mcp"}
    latest = version_model(server.id, "1.0.0", is_latest=True)
    latest.repository = {"source": "github", "url": "example/weather-mcp"}

    async def get_server(*args, **kwargs):
        return server

    async def list_versions(*args, **kwargs):
        return [latest]

    async def manifest(*args, **kwargs):
        return service.WardnOwnershipManifest(
            payload={"owners": [{"userId": str(uuid4())}]},
            source_url="https://raw.githubusercontent.com/example/weather-mcp/main/wardn.json",
        )

    monkeypatch.setattr(service.repository, "get_published_server", get_server)
    monkeypatch.setattr(service.repository, "list_published_server_versions", list_versions)
    monkeypatch.setattr(service, "fetch_wardn_ownership_manifest", manifest)

    with pytest.raises(RegistryOwnershipClaimError):
        await service.claim_server_ownership(FakeSession(), server.name, current_user)


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
async def test_delete_server_allows_direct_owner(monkeypatch) -> None:
    owner = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    server = server_model()
    server.owner_user_id = owner.id
    latest = version_model(server.id, "1.0.0", is_latest=True)

    async def get_server(*args, **kwargs):
        return server

    async def list_versions(*args, **kwargs):
        return [latest]

    async def sync_categories(*args):
        return None

    monkeypatch.setattr(service.repository, "get_server", get_server)
    monkeypatch.setattr(service.repository, "list_server_versions", list_versions)
    monkeypatch.setattr(service.repository, "sync_server_categories", sync_categories)

    await service.delete_server(
        FakeSession(),
        server.name,
        current_user=owner,
        actor_user_id=owner.id,
    )

    assert server.status == "deleted"
    assert latest.status == "deleted"


@pytest.mark.asyncio
async def test_delete_server_rejects_non_owner(monkeypatch) -> None:
    owner = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    other_user = User(id=uuid4(), email="other@example.com", is_superuser=False)
    server = server_model()
    server.owner_user_id = owner.id

    async def get_server(*args, **kwargs):
        return server

    monkeypatch.setattr(service.repository, "get_server", get_server)

    with pytest.raises(RegistryAccessDeniedError):
        await service.delete_server(FakeSession(), server.name, current_user=other_user)

    assert server.status == "active"


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

    session = FakeSession()
    actor_user_id = uuid4()

    await service.delete_server(
        session,
        "io.github.example/weather",
        actor_user_id=actor_user_id,
    )

    assert server.status == "deleted"
    assert server.current_version_id is None
    assert latest.status == "deleted"
    assert latest.is_latest is False
    assert previous.status == "deleted"
    assert previous.is_latest is False
    assert synced_categories == []
    event = next(item for item in session.added if isinstance(item, EventRecord))
    assert event.event_type == "registry.server.archived"
    assert event.actor_user_id == actor_user_id
    assert event.payload["registryServer"]["status"] == "deleted"


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
async def test_get_server_detail_hides_unpublished_server(monkeypatch) -> None:
    async def missing_server(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_published_server", missing_server)

    with pytest.raises(RegistryServerNotFoundError):
        await service.get_server_detail(FakeSession(), "io.github.example/weather")


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

    monkeypatch.setattr(service.repository, "get_published_server", get_server)
    monkeypatch.setattr(service.repository, "list_published_server_versions", list_versions)
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


@pytest.mark.asyncio
async def test_get_server_detail_omits_private_source_evidence(monkeypatch) -> None:
    now = datetime(2026, 6, 23, tzinfo=UTC)
    server = server_model()
    server.repository = {"source": "github", "url": "https://github.com/example/weather"}
    version = version_model(server.id, "1.0.0", is_latest=True)
    version.repository = {"source": "github", "url": "https://github.com/example/weather"}
    env_var = {
        "name": "WEATHER_API_KEY",
        "description": "Weather API key.",
        "source": "README.md configuration section",
    }
    version.packages = [
        {
            "registryType": "npm",
            "identifier": "@example/weather-mcp",
            "environmentVariables": [env_var],
            "packageVersionEvidence": (
                "Current package version is 0.21.0 from package.json, manifest.json, "
                "and npm registry."
            ),
            "staleVersionReferences": [
                "server.json version and package version are stale.",
            ],
            "staleVersionReferencesReviewed": True,
        }
    ]
    version.server_json = {
        **version.server_json,
        "repository": version.repository,
        "packages": version.packages,
        "_meta": {
            "categories": ["weather"],
            "importEvidence": {
                "files": ["README.md", "server.json"],
                "missing": ["source review evidence"],
            },
            "reviewNotes": "Updated after Wardn review feedback.",
            "sourceReview": {"filesRead": ["README.md"]},
            "source": "README.md",
        },
    }

    async def get_server(*args, **kwargs):
        return server

    async def list_versions(*args, **kwargs):
        return [version]

    async def empty_context(*args, **kwargs):
        return {}

    async def categories(*args, **kwargs):
        return {
            server.id: [
                RegistryCategory(
                    id=uuid4(),
                    slug="weather",
                    name="Weather",
                    description="Weather tools",
                    sort_order=100,
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            ]
        }

    monkeypatch.setattr(service.repository, "get_published_server", get_server)
    monkeypatch.setattr(service.repository, "list_published_server_versions", list_versions)
    monkeypatch.setattr(service.repository, "list_partner_support_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_for_servers", categories)
    monkeypatch.setattr(service.repository, "list_organizations_by_ids", empty_context)
    monkeypatch.setattr(service.repository, "list_users_by_ids", empty_context)

    response = await service.get_server_detail(FakeSession(), server.name)
    public_version = response.versions[0]

    assert public_version.repository == version.repository
    assert public_version.server_json["repository"] == version.repository
    assert public_version.packages[0]["environmentVariables"] == [
        {"name": "WEATHER_API_KEY", "description": "Weather API key."}
    ]
    assert "packageVersionEvidence" not in public_version.packages[0]
    assert "staleVersionReferences" not in public_version.packages[0]
    assert "staleVersionReferencesReviewed" not in public_version.packages[0]
    assert public_version.server_json["packages"][0]["environmentVariables"] == [
        {"name": "WEATHER_API_KEY", "description": "Weather API key."}
    ]
    assert "packageVersionEvidence" not in public_version.server_json["packages"][0]
    assert "staleVersionReferences" not in public_version.server_json["packages"][0]
    assert "staleVersionReferencesReviewed" not in public_version.server_json["packages"][0]
    assert public_version.server_json["_meta"] == {"categories": ["weather"]}


@pytest.mark.asyncio
async def test_get_server_overview_tab_includes_public_target_metadata(monkeypatch) -> None:
    server = server_model()
    server.repository = {"source": "github", "url": "https://github.com/example/weather"}
    version = version_model(server.id, "1.0.0", is_latest=True)
    version.quality_score = 78
    version.repository = server.repository
    version.packages = [
        {
            "registryType": "npm",
            "identifier": "@example/weather-mcp",
            "transport": {"type": "stdio", "command": "npx", "args": ["@example/weather-mcp"]},
            "environmentVariables": [
                {
                    "name": "WEATHER_API_KEY",
                    "description": "Weather API key.",
                    "source": "README.md",
                }
            ],
            "packageVersionEvidence": "Private reviewer note.",
        }
    ]
    version.remotes = [{"type": "streamable-http", "url": "https://weather.example/mcp"}]
    version.server_json = {
        **version.server_json,
        "repository": version.repository,
        "packages": version.packages,
        "remotes": version.remotes,
        "_meta": {
            "categories": ["weather"],
            "sourceReview": {"filesRead": ["README.md"]},
        },
    }

    async def get_server(*args, **kwargs):
        return server

    async def list_versions(*args, **kwargs):
        return [version]

    async def empty_context(*args, **kwargs):
        return {}

    monkeypatch.setattr(service.repository, "get_published_server", get_server)
    monkeypatch.setattr(service.repository, "list_published_server_versions", list_versions)
    monkeypatch.setattr(service.repository, "list_partner_support_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_for_servers", empty_context)
    monkeypatch.setattr(service.repository, "list_categories_by_slugs", categories_by_slug)
    monkeypatch.setattr(service.repository, "list_organizations_by_ids", empty_context)
    monkeypatch.setattr(service.repository, "list_users_by_ids", empty_context)

    response = await service.get_server_overview_tab(FakeSession(), server.name)
    public_version = response.versions[0]

    assert public_version.registry_namespace.namespace == "io.github.example"
    assert public_version.quality_score == 78
    assert public_version.trust_report is not None
    assert public_version.packages[0]["environmentVariables"] == [
        {"name": "WEATHER_API_KEY", "description": "Weather API key."}
    ]
    assert "packageVersionEvidence" not in public_version.packages[0]
    assert public_version.remotes == version.remotes
    assert public_version.server_json["packages"][0]["environmentVariables"] == [
        {"name": "WEATHER_API_KEY", "description": "Weather API key."}
    ]
    assert "packageVersionEvidence" not in public_version.server_json["packages"][0]
    assert public_version.server_json["_meta"] == {"categories": ["weather"]}
