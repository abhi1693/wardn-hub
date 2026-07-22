from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.registry import repository
from app.modules.registry.models import RegistryServer


class EmptyScalarResult:
    def unique(self):
        return self

    def all(self) -> list[object]:
        return []


class EmptyExecuteResult:
    def scalars(self) -> EmptyScalarResult:
        return EmptyScalarResult()

    def all(self) -> list[object]:
        return []

    def scalar_one_or_none(self) -> None:
        return None


class CaptureSession:
    def __init__(self) -> None:
        self.statements: list[object] = []
        self.added: list[object] = []

    async def execute(self, statement) -> EmptyExecuteResult:
        self.statements.append(statement)
        return EmptyExecuteResult()

    async def scalar(self, statement) -> int:
        self.statements.append(statement)
        return 0

    def add(self, instance: object) -> None:
        self.added.append(instance)


class StatsExecuteResult:
    def __init__(self, last_registry_update: datetime) -> None:
        self.last_registry_update = last_registry_update

    def one(self) -> tuple[int, int, datetime]:
        return 1575, 50, self.last_registry_update


class StatsCaptureSession(CaptureSession):
    def __init__(self, last_registry_update: datetime) -> None:
        super().__init__()
        self.last_registry_update = last_registry_update

    async def execute(self, statement) -> StatsExecuteResult:
        self.statements.append(statement)
        return StatsExecuteResult(self.last_registry_update)


def sql(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


@pytest.mark.asyncio
async def test_list_servers_uses_published_filters_when_syncing_updates() -> None:
    session = CaptureSession()

    servers, next_cursor = await repository.list_servers(
        session,
        offset=0,
        limit=50,
        include_deleted=True,
        updated_since=datetime(2026, 6, 1, tzinfo=UTC),
    )

    statement = sql(session.statements[0])
    assert servers == []
    assert next_cursor == ""
    assert "mcp_servers.status = 'active'" in statement
    assert "mcp_servers.visibility = 'public'" in statement
    assert "mcp_servers.current_version_id IS NOT NULL" in statement
    assert "mcp_server_versions.status = 'active'" in statement
    assert "mcp_server_versions.is_latest IS true" in statement
    assert "mcp_servers.status = 'deleted'" not in statement


def test_registry_search_normalization_drops_only_generic_catalog_terms() -> None:
    assert repository.normalize_registry_search_query("argocd") == "argocd"
    assert repository.normalize_registry_search_query("ArgoCD MCP Server") == "argocd"
    assert (
        repository.normalize_registry_search_query("ArgoCD Model Context Protocol server")
        == "argocd"
    )
    assert repository.normalize_registry_search_query("mcp server") == "mcp server"
    assert (
        repository.normalize_registry_search_query("cloudformation best practices")
        == "cloudformation best practices"
    )


@pytest.mark.asyncio
async def test_list_servers_uses_indexed_ranked_search_with_normalized_terms() -> None:
    session = CaptureSession()

    await repository.list_servers(
        session,
        offset=0,
        limit=25,
        include_deleted=False,
        search="argocd mcp server",
    )

    statement = sql(session.statements[0])
    assert (
        "mcp_servers.search_vector @@ "
        "websearch_to_tsquery('english'::regconfig, 'argocd')" in statement
    )
    assert (
        "mcp_servers.search_vector @@ "
        "websearch_to_tsquery('simple'::regconfig, 'argocd')" in statement
    )
    assert "ts_rank_cd(mcp_servers.search_vector" in statement
    assert "argocd mcp server" not in statement
    assert "mcp_servers.description ILIKE" not in statement
    assert "ORDER BY CASE" in statement


@pytest.mark.asyncio
async def test_registry_stats_uses_one_aggregate_published_query() -> None:
    last_registry_update = datetime(2026, 7, 22, tzinfo=UTC)
    session = StatsCaptureSession(last_registry_update)

    stats = await repository.get_registry_stats(session)

    statement = sql(session.statements[0])
    assert stats == (1575, 50, last_registry_update)
    assert len(session.statements) == 1
    assert "count(mcp_servers.id)" in statement
    assert "count(mcp_categories.id)" in statement
    assert "max(greatest(mcp_servers.updated_at, mcp_server_versions.published_at))" in statement
    assert "mcp_servers.status = 'active'" in statement
    assert "mcp_servers.visibility = 'public'" in statement
    assert "mcp_server_versions.is_latest IS true" in statement


@pytest.mark.asyncio
async def test_list_servers_rejects_non_active_public_status_filter_without_query() -> None:
    session = CaptureSession()

    servers, next_cursor = await repository.list_servers(
        session,
        offset=0,
        limit=50,
        include_deleted=False,
        status="deleted",
    )

    assert servers == []
    assert next_cursor == ""
    assert session.statements == []


@pytest.mark.asyncio
async def test_list_servers_version_filter_requires_active_matching_version() -> None:
    session = CaptureSession()

    await repository.list_servers(
        session,
        offset=0,
        limit=50,
        include_deleted=False,
        version="0.9.0",
    )

    statement = sql(session.statements[0])
    assert "mcp_server_versions_1.version = '0.9.0'" in statement
    assert "mcp_server_versions_1.status = 'active'" in statement


@pytest.mark.asyncio
async def test_list_published_servers_uses_published_filters_for_count_and_rows() -> None:
    session = CaptureSession()

    rows, total = await repository.list_published_servers(session, offset=20, limit=20)

    assert rows == []
    assert total == 0
    assert len(session.statements) == 2
    for statement in (sql(session.statements[0]), sql(session.statements[1])):
        assert "mcp_servers.status = 'active'" in statement
        assert "mcp_servers.visibility = 'public'" in statement
        assert "mcp_servers.current_version_id IS NOT NULL" in statement
        assert "mcp_server_versions.status = 'active'" in statement
        assert "mcp_server_versions.is_latest IS true" in statement


@pytest.mark.asyncio
async def test_list_current_versions_loads_only_selected_current_ids() -> None:
    session = CaptureSession()
    first = RegistryServer(id=uuid4(), name="io.github.example/weather")
    first.current_version_id = uuid4()
    second = RegistryServer(id=uuid4(), name="io.github.example/calendar")
    second.current_version_id = uuid4()

    versions = await repository.list_current_versions_for_servers(
        session, [first, second]
    )

    statement = sql(session.statements[0])
    assert versions == {}
    assert str(first.current_version_id) in statement
    assert str(second.current_version_id) in statement
    assert "mcp_server_versions.status = 'active'" in statement
    assert "mcp_server_versions.server_id IN" not in statement


@pytest.mark.asyncio
async def test_get_published_server_version_requires_active_current_latest() -> None:
    session = CaptureSession()
    server = RegistryServer(id=uuid4(), name="io.github.example/weather")
    server.current_version_id = uuid4()

    version = await repository.get_published_server_version(session, server, "latest")

    statement = sql(session.statements[0])
    assert version is None
    assert "mcp_server_versions.status = 'active'" in statement
    assert "mcp_server_versions.id = '" in statement
    assert "mcp_server_versions.is_latest IS true" in statement


@pytest.mark.asyncio
async def test_public_registry_users_require_public_current_versions() -> None:
    session = CaptureSession()

    users = await repository.list_public_registry_users(session)

    statement = sql(session.statements[0])
    assert users == []
    assert "mcp_servers.visibility = 'public'" in statement
    assert "mcp_server_versions.id = mcp_servers.current_version_id" in statement
    assert "mcp_servers.current_version_id IS NOT NULL" in statement
    assert "mcp_server_versions.status = 'active'" in statement
    assert "mcp_server_versions.is_latest IS true" in statement


@pytest.mark.asyncio
async def test_sync_server_categories_does_not_create_unknown_category_slugs() -> None:
    session = CaptureSession()

    await repository.sync_server_categories(
        session,
        uuid4(),
        ["ai-and-llm-integration", "not-in-wardn-taxonomy"],
    )

    statement = sql(session.statements[1])
    assert "other-tools-integrations" in statement
    assert "ai-and-llm-integration" not in statement
    assert "not-in-wardn-taxonomy" not in statement
    assert session.added == []


@pytest.mark.asyncio
async def test_sync_server_categories_ignores_unknown_slugs_when_known_slugs_exist() -> None:
    session = CaptureSession()

    await repository.sync_server_categories(
        session,
        uuid4(),
        ["developer-tools", "ai-and-llm-integration"],
    )

    statement = sql(session.statements[1])
    assert "developer-tools" in statement
    assert "ai-and-llm-integration" not in statement
    assert "other-tools-integrations" not in statement
    assert session.added == []


@pytest.mark.asyncio
async def test_list_servers_for_user_uses_published_filters() -> None:
    session = CaptureSession()
    user_id = uuid4()

    servers, next_cursor = await repository.list_servers_for_user(
        session,
        user_id,
        offset=0,
        limit=50,
    )

    statement = sql(session.statements[0])
    assert servers == []
    assert next_cursor == ""
    assert "mcp_servers.status = 'active'" in statement
    assert "mcp_servers.visibility = 'public'" in statement
    assert "mcp_servers.current_version_id IS NOT NULL" in statement
    assert "mcp_server_versions.status = 'active'" in statement
    assert "mcp_server_versions.is_latest IS true" in statement
