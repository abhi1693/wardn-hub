from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.registry.models import RegistryServer, RegistryServerVersion


def visible_servers_query(include_deleted: bool) -> Select[tuple[RegistryServer]]:
    statement = select(RegistryServer)
    if not include_deleted:
        statement = statement.where(RegistryServer.status != "deleted")
    return statement


def visible_versions_query(include_deleted: bool) -> Select[tuple[RegistryServerVersion]]:
    statement = select(RegistryServerVersion)
    if not include_deleted:
        statement = statement.where(RegistryServerVersion.status != "deleted")
    return statement


async def get_server(
    session: AsyncSession,
    name: str,
    *,
    include_deleted: bool = False,
) -> RegistryServer | None:
    result = await session.execute(
        visible_servers_query(include_deleted).where(RegistryServer.name == name)
    )
    return result.scalar_one_or_none()


async def get_server_by_id(session: AsyncSession, server_id: UUID) -> RegistryServer | None:
    result = await session.execute(select(RegistryServer).where(RegistryServer.id == server_id))
    return result.scalar_one_or_none()


async def get_server_version(
    session: AsyncSession,
    name: str,
    version: str,
    *,
    include_deleted: bool = False,
) -> RegistryServerVersion | None:
    statement = visible_versions_query(include_deleted).where(RegistryServerVersion.name == name)
    if version == "latest":
        statement = statement.where(RegistryServerVersion.is_latest.is_(True))
    else:
        statement = statement.where(RegistryServerVersion.version == version)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def list_servers(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    include_deleted: bool,
    search: str | None = None,
    updated_since: datetime | None = None,
    version: str | None = "latest",
    support_level: str | None = None,
    partner: bool | None = None,
    registry_type: str | None = None,
    transport_type: str | None = None,
    status: str | None = None,
) -> tuple[list[RegistryServer], str]:
    statement = visible_servers_query(include_deleted or updated_since is not None)
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                RegistryServer.name.ilike(pattern),
                RegistryServer.title.ilike(pattern),
                RegistryServer.description.ilike(pattern),
            )
        )
    if updated_since:
        statement = statement.where(RegistryServer.updated_at >= updated_since)
    if status:
        statement = statement.where(RegistryServer.status == status)

    if version and version != "latest":
        statement = statement.join(
            RegistryServerVersion,
            RegistryServerVersion.server_id == RegistryServer.id,
        ).where(RegistryServerVersion.version == version)

    # Phase 1 stores packages/remotes as JSONB but keeps advanced support/partner
    # filters as no-ops until trust-plane tables land in later phases.
    _ = support_level, partner, registry_type, transport_type

    statement = statement.order_by(RegistryServer.name.asc())
    result = await session.execute(statement.offset(offset).limit(limit + 1))
    rows = list(result.scalars().unique().all())
    next_cursor = str(offset + limit) if len(rows) > limit else ""
    return rows[:limit], next_cursor


async def list_server_versions(
    session: AsyncSession,
    name: str,
    *,
    include_deleted: bool = False,
) -> list[RegistryServerVersion]:
    result = await session.execute(
        visible_versions_query(include_deleted)
        .where(RegistryServerVersion.name == name)
        .order_by(
            RegistryServerVersion.is_latest.desc(),
            RegistryServerVersion.published_at.desc(),
            RegistryServerVersion.version.desc(),
        )
    )
    return list(result.scalars().all())


async def count_versions_for_name(session: AsyncSession, name: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(RegistryServerVersion)
        .where(RegistryServerVersion.name == name)
    )
    return result.scalar_one()


async def clear_latest_for_server(session: AsyncSession, server_id: UUID) -> None:
    await session.execute(
        update(RegistryServerVersion)
        .where(RegistryServerVersion.server_id == server_id)
        .values(is_latest=False)
    )


async def latest_visible_version(
    session: AsyncSession,
    server_id: UUID,
) -> RegistryServerVersion | None:
    result = await session.execute(
        visible_versions_query(False)
        .where(RegistryServerVersion.server_id == server_id)
        .order_by(RegistryServerVersion.published_at.desc(), RegistryServerVersion.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()

