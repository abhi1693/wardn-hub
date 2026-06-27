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

    async def execute(self, statement) -> EmptyExecuteResult:
        self.statements.append(statement)
        return EmptyExecuteResult()

    async def scalar(self, statement) -> int:
        self.statements.append(statement)
        return 0


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
    assert "mcp_servers.current_version_id = mcp_server_versions.id" in statement
    assert "mcp_server_versions.status = 'active'" in statement
