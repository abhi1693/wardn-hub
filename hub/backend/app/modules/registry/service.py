from datetime import UTC, datetime

from app.modules.registry import repository
from app.modules.registry.exceptions import (
    DuplicateRegistryVersionError,
    InvalidRegistryCursorError,
    RegistryServerNotFoundError,
    RegistryVersionNotFoundError,
)
from app.modules.registry.models import RegistryServer, RegistryServerVersion
from app.modules.registry.schemas import (
    MCPServerDocument,
    RegistryLatestVersionSummary,
    RegistryListMetadata,
    RegistryServerDetailResponse,
    RegistryServerListResponse,
    RegistryServerRead,
    RegistryServerVersionCreate,
    RegistryServerVersionDetailResponse,
    RegistryServerVersionListResponse,
    RegistryServerVersionRead,
    RegistryServerVersionUpdate,
)


def parse_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise InvalidRegistryCursorError("invalid registry cursor") from exc
    if offset < 0:
        raise InvalidRegistryCursorError("invalid registry cursor")
    return offset


def document_values(payload: MCPServerDocument) -> dict:
    return {
        "name": payload.name,
        "title": payload.title,
        "description": payload.description,
        "version": payload.version,
        "website_url": payload.website_url,
        "repository": payload.repository,
        "packages": payload.packages,
        "remotes": payload.remotes,
        "icons": payload.icons,
        "server_json": payload.model_dump(by_alias=True, exclude_none=True),
    }


def server_summary(
    server: RegistryServer,
    latest_version: RegistryServerVersion | None = None,
) -> RegistryServerRead:
    latest = None
    if latest_version is not None:
        latest = RegistryLatestVersionSummary(
            id=latest_version.id,
            version=latest_version.version,
            status=latest_version.status,
            published_at=latest_version.published_at,
            published_by=None,
        )
    return RegistryServerRead(
        id=server.id,
        name=server.name,
        title=server.title,
        description=server.description,
        website_url=server.website_url,
        repository=server.repository,
        icons=server.icons,
        status=server.status,
        status_message=server.status_message,
        visibility=server.visibility,
        latest_version=latest,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


def version_summary(version: RegistryServerVersion) -> RegistryServerVersionRead:
    return RegistryServerVersionRead(
        id=version.id,
        server_id=version.server_id,
        name=version.name,
        version=version.version,
        title=version.title,
        description=version.description,
        website_url=version.website_url,
        repository=version.repository,
        packages=version.packages,
        remotes=version.remotes,
        icons=version.icons,
        server_json=version.server_json,
        status=version.status,
        status_message=version.status_message,
        is_latest=version.is_latest,
        published_at=version.published_at,
        status_changed_at=version.status_changed_at,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


async def server_with_latest(session, server: RegistryServer) -> RegistryServerRead:
    latest = None
    if server.current_version_id:
        latest = await repository.get_server_version(session, server.name, "latest")
    return server_summary(server, latest)


async def create_server_version(
    session,
    payload: RegistryServerVersionCreate,
) -> RegistryServerVersionDetailResponse:
    existing_version = await repository.get_server_version(
        session,
        payload.name,
        payload.version,
        include_deleted=True,
    )
    if existing_version is not None and existing_version.status != "deleted":
        raise DuplicateRegistryVersionError("server version already exists")

    server = await repository.get_server(session, payload.name, include_deleted=True)
    values = document_values(payload)
    now = datetime.now(UTC)

    if server is None:
        server = RegistryServer(
            name=payload.name,
            title=payload.title,
            description=payload.description,
            website_url=payload.website_url,
            repository=payload.repository,
            icons=payload.icons,
            status="active",
            status_message="",
            visibility="public",
        )
        session.add(server)
        await session.flush()
        await session.refresh(server)
    else:
        server.title = payload.title
        server.description = payload.description
        server.website_url = payload.website_url
        server.repository = payload.repository
        server.icons = payload.icons
        if server.status == "deleted":
            server.status = "active"
            server.status_message = ""

    await repository.clear_latest_for_server(session, server.id)

    if existing_version is not None:
        for key, value in values.items():
            if key != "version":
                setattr(existing_version, key, value)
        existing_version.status = "active"
        existing_version.status_message = ""
        existing_version.is_latest = True
        existing_version.status_changed_at = now
        version = existing_version
    else:
        version = RegistryServerVersion(
            server_id=server.id,
            **values,
            status="active",
            status_message="",
            is_latest=True,
            published_at=now,
            status_changed_at=now,
        )
        session.add(version)

    await session.flush()
    await session.refresh(version)
    server.current_version_id = version.id
    await session.flush()
    await session.refresh(server)
    return RegistryServerVersionDetailResponse(
        server=server_summary(server, version),
        version=version_summary(version),
    )


async def update_server_version(
    session,
    name: str,
    version_name: str,
    payload: RegistryServerVersionUpdate,
) -> RegistryServerVersionDetailResponse:
    if payload.name != name or payload.version != version_name:
        raise RegistryVersionNotFoundError("server version does not match request path")

    version = await repository.get_server_version(
        session,
        name,
        version_name,
        include_deleted=True,
    )
    if version is None:
        raise RegistryVersionNotFoundError("server version not found")

    server = await repository.get_server_by_id(session, version.server_id)
    if server is None:
        raise RegistryServerNotFoundError("server not found")

    for key, value in document_values(payload).items():
        setattr(version, key, value)
    if version.status == "deleted":
        version.status = "active"
        version.status_message = ""
        version.status_changed_at = datetime.now(UTC)

    if version.is_latest:
        server.title = payload.title
        server.description = payload.description
        server.website_url = payload.website_url
        server.repository = payload.repository
        server.icons = payload.icons

    await session.flush()
    await session.refresh(version)
    await session.refresh(server)
    return RegistryServerVersionDetailResponse(
        server=server_summary(server, version if version.is_latest else None),
        version=version_summary(version),
    )


async def delete_server_version(session, name: str, version_name: str) -> None:
    version = await repository.get_server_version(
        session,
        name,
        version_name,
        include_deleted=True,
    )
    if version is None:
        raise RegistryVersionNotFoundError("server version not found")
    if version.status == "deleted":
        return

    server = await repository.get_server_by_id(session, version.server_id)
    if server is None:
        raise RegistryServerNotFoundError("server not found")

    was_latest = version.is_latest
    version.status = "deleted"
    version.status_message = "Deleted from Wardn Hub."
    version.is_latest = False
    version.status_changed_at = datetime.now(UTC)

    if was_latest:
        replacement = await repository.latest_visible_version(session, server.id)
        if replacement is not None:
            replacement.is_latest = True
            server.current_version_id = replacement.id
            server.title = replacement.title
            server.description = replacement.description
            server.website_url = replacement.website_url
            server.repository = replacement.repository
            server.icons = replacement.icons
        else:
            server.status = "deleted"
            server.status_message = "All versions deleted from Wardn Hub."
            server.current_version_id = None

    await session.flush()


async def set_latest_version(
    session,
    name: str,
    version_name: str,
) -> RegistryServerVersionDetailResponse:
    version = await repository.get_server_version(session, name, version_name)
    if version is None:
        raise RegistryVersionNotFoundError("server version not found")
    server = await repository.get_server_by_id(session, version.server_id)
    if server is None:
        raise RegistryServerNotFoundError("server not found")

    await repository.clear_latest_for_server(session, server.id)
    version.is_latest = True
    server.current_version_id = version.id
    server.title = version.title
    server.description = version.description
    server.website_url = version.website_url
    server.repository = version.repository
    server.icons = version.icons
    await session.flush()
    await session.refresh(version)
    await session.refresh(server)
    return RegistryServerVersionDetailResponse(
        server=server_summary(server, version),
        version=version_summary(version),
    )


async def list_servers(
    session,
    *,
    cursor: str | None,
    limit: int,
    include_deleted: bool,
    search: str | None = None,
    updated_since=None,
    version: str | None = "latest",
    support_level: str | None = None,
    partner: bool | None = None,
    registry_type: str | None = None,
    transport_type: str | None = None,
    status: str | None = None,
) -> RegistryServerListResponse:
    offset = parse_cursor(cursor)
    servers, next_cursor = await repository.list_servers(
        session,
        offset=offset,
        limit=limit,
        include_deleted=include_deleted,
        search=search,
        updated_since=updated_since,
        version=version,
        support_level=support_level,
        partner=partner,
        registry_type=registry_type,
        transport_type=transport_type,
        status=status,
    )
    return RegistryServerListResponse(
        servers=[await server_with_latest(session, server) for server in servers],
        metadata=RegistryListMetadata(count=len(servers), next_cursor=next_cursor),
    )


async def get_server_detail(
    session,
    name: str,
    *,
    include_deleted: bool = False,
) -> RegistryServerDetailResponse:
    server = await repository.get_server(session, name, include_deleted=include_deleted)
    if server is None:
        raise RegistryServerNotFoundError("server not found")
    versions = await repository.list_server_versions(
        session,
        name,
        include_deleted=include_deleted,
    )
    latest = next((candidate for candidate in versions if candidate.is_latest), None)
    return RegistryServerDetailResponse(
        server=server_summary(server, latest),
        versions=[version_summary(version) for version in versions],
    )


async def list_versions(
    session,
    name: str,
    *,
    include_deleted: bool = False,
) -> RegistryServerVersionListResponse:
    versions = await repository.list_server_versions(
        session,
        name,
        include_deleted=include_deleted,
    )
    if not versions and await repository.count_versions_for_name(session, name) == 0:
        raise RegistryServerNotFoundError("server not found")
    return RegistryServerVersionListResponse(
        versions=[version_summary(version) for version in versions],
        metadata=RegistryListMetadata(count=len(versions)),
    )


async def get_version_detail(
    session,
    name: str,
    version_name: str,
    *,
    include_deleted: bool = False,
) -> RegistryServerVersionDetailResponse:
    version = await repository.get_server_version(
        session,
        name,
        version_name,
        include_deleted=include_deleted,
    )
    if version is None:
        raise RegistryVersionNotFoundError("server version not found")
    server = await repository.get_server_by_id(session, version.server_id)
    if server is None:
        raise RegistryServerNotFoundError("server not found")
    latest = (
        version
        if version.is_latest
        else await repository.get_server_version(session, name, "latest")
    )
    return RegistryServerVersionDetailResponse(
        server=server_summary(server, latest),
        version=version_summary(version),
    )
