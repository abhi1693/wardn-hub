import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.modules.registry import repository
from app.modules.registry.category_seed import MCP_SERVERS_CATEGORY_SEEDS
from app.modules.registry.exceptions import (
    DuplicateRegistryCategoryError,
    DuplicateRegistryVersionError,
    InvalidRegistryCursorError,
    RegistryCategoryNotFoundError,
    RegistryServerNotFoundError,
    RegistryVersionNotFoundError,
)
from app.modules.registry.models import RegistryCategory, RegistryServer, RegistryServerVersion
from app.modules.registry.schemas import (
    ActorSummary,
    MCPServerDocument,
    PartnerSupportSummary,
    RegistryCategoryCreate,
    RegistryCategoryListResponse,
    RegistryCategoryRead,
    RegistryCategoryUpdate,
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
    RegistryUserDetailResponse,
    RegistryUserListResponse,
    RegistryUserRead,
)
from app.modules.users.exceptions import UserNotFoundError


@dataclass
class RegistryTrustContext:
    users: dict[UUID, object]
    organizations: dict[UUID, object]
    partner_support: dict[str, list[tuple[object, object]]]
    categories: dict[UUID, list[RegistryCategory]]


EMPTY_TRUST_CONTEXT = RegistryTrustContext(
    users={},
    organizations={},
    partner_support={},
    categories={},
)


PUBLISHER_META_KEY = "io.modelcontextprotocol.registry/publisher-provided"


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
        "documentation": payload.documentation,
        "version": payload.version,
        "website_url": payload.website_url,
        "repository": payload.repository,
        "packages": payload.packages,
        "remotes": payload.remotes,
        "icons": payload.icons,
        "server_json": payload.model_dump(by_alias=True, exclude_none=True),
    }


def category_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "other"


def category_values_from_metadata(metadata: dict) -> list[str]:
    publisher_metadata = metadata.get(PUBLISHER_META_KEY, {})
    if not isinstance(publisher_metadata, dict):
        return []

    raw_values = []
    category = publisher_metadata.get("category")
    categories = publisher_metadata.get("categories")
    if isinstance(category, str):
        raw_values.append(category)
    if isinstance(categories, list):
        raw_values.extend(value for value in categories if isinstance(value, str))

    slugs = []
    seen = set()
    for value in raw_values:
        slug = category_slug(value)
        if slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    return slugs


def category_values(payload: MCPServerDocument) -> list[str]:
    return category_values_from_metadata(payload.meta or {})


def category_values_from_server_json(server_json: dict) -> list[str]:
    metadata = server_json.get("_meta", {})
    return category_values_from_metadata(metadata if isinstance(metadata, dict) else {})


def public_user_name(user) -> str:
    return f"{user.first_name} {user.last_name}".strip()


def public_user_login(user) -> str:
    return public_user_name(user) or str(user.id)


def actor_summary_for_user(user) -> ActorSummary:
    return ActorSummary(
        id=user.id,
        login=public_user_login(user),
        type="User",
        name=public_user_name(user),
        url=f"/api/v1/users/{user.id}",
        htmlUrl=f"/users/{user.id}",
    )


def public_user_summary(user) -> RegistryUserRead:
    return RegistryUserRead(
        id=user.id,
        login=public_user_login(user),
        name=public_user_name(user),
        htmlUrl=f"/users/{user.id}",
    )


def actor_summary_for_organization(organization) -> ActorSummary:
    return ActorSummary(
        id=organization.id,
        login=organization.slug,
        type="Organization",
        name=organization.name,
        url=f"/api/v1/organizations/{organization.id}",
        htmlUrl=f"/{organization.slug}",
    )


def user_actor(user_id: UUID | None, trust: RegistryTrustContext) -> ActorSummary | None:
    if user_id is None:
        return None
    user = trust.users.get(user_id)
    return actor_summary_for_user(user) if user is not None else None


def organization_actor(
    organization_id: UUID | None,
    trust: RegistryTrustContext,
) -> ActorSummary | None:
    if organization_id is None:
        return None
    organization = trust.organizations.get(organization_id)
    return actor_summary_for_organization(organization) if organization is not None else None


def owner_actor(
    *,
    owner_user_id: UUID | None,
    owner_organization_id: UUID | None,
    trust: RegistryTrustContext,
) -> ActorSummary | None:
    return organization_actor(owner_organization_id, trust) or user_actor(owner_user_id, trust)


def partner_support_summary(
    server_name: str,
    trust: RegistryTrustContext,
    owner_organization_id: UUID | None = None,
) -> list[PartnerSupportSummary]:
    summaries = []
    seen_organization_ids: set[UUID] = set()
    owner_organization = (
        trust.organizations.get(owner_organization_id)
        if owner_organization_id is not None
        else None
    )
    for support, organization in trust.partner_support.get(server_name, []):
        summaries.append(
            PartnerSupportSummary(
                organization=actor_summary_for_organization(organization),
                supportLevel=support.support_level,
                supportStatus=support.support_status,
                supportUrl=support.support_url,
                docsUrl=support.docs_url,
                startsAt=support.starts_at,
                endsAt=support.ends_at,
            )
        )
        seen_organization_ids.add(organization.id)

    if (
        owner_organization is not None
        and owner_organization.is_partner
        and owner_organization.partner_status == "active"
        and owner_organization.id not in seen_organization_ids
    ):
        summaries.append(
            PartnerSupportSummary(
                organization=actor_summary_for_organization(owner_organization),
                supportLevel=owner_organization.partner_support_level or "compatible",
                supportStatus="active",
                supportUrl=owner_organization.website_url,
                docsUrl="",
                startsAt=None,
                endsAt=None,
            )
        )
        seen_organization_ids.add(owner_organization.id)
    return summaries


def category_summary(category: RegistryCategory) -> RegistryCategoryRead:
    return RegistryCategoryRead(
        id=category.id,
        slug=category.slug,
        name=category.name,
        description=category.description,
        sortOrder=category.sort_order,
    )


def next_category_sort_order(
    existing_orders: list[int],
    requested_order: int | None = None,
) -> int:
    used_orders = set(existing_orders)
    candidate = (
        requested_order if requested_order is not None else (max(used_orders, default=0) + 10)
    )
    while candidate in used_orders:
        candidate += 10
    return candidate


def categories_for_server(
    server_id: UUID,
    trust: RegistryTrustContext,
) -> list[RegistryCategoryRead]:
    return [category_summary(category) for category in trust.categories.get(server_id, [])]


async def build_trust_context(
    session,
    *,
    servers: list[RegistryServer] | None = None,
    versions: list[RegistryServerVersion] | None = None,
) -> RegistryTrustContext:
    servers = servers or []
    versions = versions or []
    user_ids: set[UUID] = set()
    organization_ids: set[UUID] = set()
    server_names = {server.name for server in servers} | {version.name for version in versions}

    for server in servers:
        for user_id in (server.owner_user_id, server.created_by_user_id, server.updated_by_user_id):
            if user_id is not None:
                user_ids.add(user_id)
        if server.owner_organization_id is not None:
            organization_ids.add(server.owner_organization_id)

    for version in versions:
        for user_id in (
            version.owner_user_id,
            version.created_by_user_id,
            version.updated_by_user_id,
            version.publisher_user_id,
        ):
            if user_id is not None:
                user_ids.add(user_id)
        if version.owner_organization_id is not None:
            organization_ids.add(version.owner_organization_id)

    partner_support = await repository.list_partner_support_for_servers(session, server_names)
    for records in partner_support.values():
        for _support, organization in records:
            organization_ids.add(organization.id)

    categories = await repository.list_categories_for_servers(
        session,
        {server.id for server in servers} | {version.server_id for version in versions},
    )

    return RegistryTrustContext(
        users=await repository.list_users_by_ids(session, user_ids),
        organizations=await repository.list_organizations_by_ids(session, organization_ids),
        partner_support=partner_support,
        categories=categories,
    )


def server_summary(
    server: RegistryServer,
    latest_version: RegistryServerVersion | None = None,
    *,
    trust: RegistryTrustContext = EMPTY_TRUST_CONTEXT,
) -> RegistryServerRead:
    latest = None
    if latest_version is not None:
        latest = RegistryLatestVersionSummary(
            id=latest_version.id,
            version=latest_version.version,
            status=latest_version.status,
            published_at=latest_version.published_at,
            published_by=user_actor(latest_version.publisher_user_id, trust),
        )
    return RegistryServerRead(
        id=server.id,
        name=server.name,
        title=server.title,
        description=server.description,
        documentation=server.documentation,
        website_url=server.website_url,
        repository=server.repository,
        icons=server.icons,
        status=server.status,
        status_message=server.status_message,
        visibility=server.visibility,
        owner=owner_actor(
            owner_user_id=server.owner_user_id,
            owner_organization_id=server.owner_organization_id,
            trust=trust,
        ),
        organization=organization_actor(server.owner_organization_id, trust),
        created_by=user_actor(server.created_by_user_id, trust),
        updated_by=user_actor(server.updated_by_user_id, trust),
        latest_version=latest,
        categories=categories_for_server(server.id, trust),
        partner_support=partner_support_summary(
            server.name,
            trust,
            server.owner_organization_id,
        ),
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


def version_summary(
    version: RegistryServerVersion,
    *,
    trust: RegistryTrustContext = EMPTY_TRUST_CONTEXT,
) -> RegistryServerVersionRead:
    return RegistryServerVersionRead(
        id=version.id,
        server_id=version.server_id,
        name=version.name,
        version=version.version,
        title=version.title,
        description=version.description,
        documentation=version.documentation,
        website_url=version.website_url,
        repository=version.repository,
        packages=version.packages,
        remotes=version.remotes,
        icons=version.icons,
        server_json=version.server_json,
        status=version.status,
        status_message=version.status_message,
        is_latest=version.is_latest,
        owner=owner_actor(
            owner_user_id=version.owner_user_id,
            owner_organization_id=version.owner_organization_id,
            trust=trust,
        ),
        organization=organization_actor(version.owner_organization_id, trust),
        created_by=user_actor(version.created_by_user_id, trust),
        updated_by=user_actor(version.updated_by_user_id, trust),
        published_by=user_actor(version.publisher_user_id, trust),
        categories=categories_for_server(version.server_id, trust),
        partner_support=partner_support_summary(
            version.name,
            trust,
            version.owner_organization_id,
        ),
        published_at=version.published_at,
        status_changed_at=version.status_changed_at,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


async def server_with_latest(session, server: RegistryServer) -> RegistryServerRead:
    latest = None
    if server.current_version_id:
        latest = await repository.get_server_version(session, server.name, "latest")
    trust = await build_trust_context(
        session,
        servers=[server],
        versions=[latest] if latest else [],
    )
    return server_summary(server, latest, trust=trust)


async def create_server_version(
    session,
    payload: RegistryServerVersionCreate,
    *,
    owner_user_id: UUID | None = None,
    owner_organization_id: UUID | None = None,
    created_by_user_id: UUID | None = None,
    updated_by_user_id: UUID | None = None,
    publisher_user_id: UUID | None = None,
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
            owner_user_id=owner_user_id,
            owner_organization_id=owner_organization_id,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=updated_by_user_id,
            title=payload.title,
            description=payload.description,
            documentation=payload.documentation,
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
        if owner_user_id is not None or owner_organization_id is not None:
            server.owner_user_id = owner_user_id
            server.owner_organization_id = owner_organization_id
        if updated_by_user_id is not None:
            server.updated_by_user_id = updated_by_user_id
        server.title = payload.title
        server.description = payload.description
        server.documentation = payload.documentation
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
        if owner_user_id is not None or owner_organization_id is not None:
            existing_version.owner_user_id = owner_user_id
            existing_version.owner_organization_id = owner_organization_id
        if updated_by_user_id is not None:
            existing_version.updated_by_user_id = updated_by_user_id
        if publisher_user_id is not None:
            existing_version.publisher_user_id = publisher_user_id
        existing_version.status_changed_at = now
        version = existing_version
    else:
        version = RegistryServerVersion(
            server_id=server.id,
            **values,
            owner_user_id=owner_user_id,
            owner_organization_id=owner_organization_id,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=updated_by_user_id,
            publisher_user_id=publisher_user_id,
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
    await repository.sync_server_categories(session, server.id, category_values(payload))
    await session.flush()
    await session.refresh(server)
    trust = await build_trust_context(session, servers=[server], versions=[version])
    return RegistryServerVersionDetailResponse(
        server=server_summary(server, version, trust=trust),
        version=version_summary(version, trust=trust),
    )


async def update_server_version(
    session,
    name: str,
    version_name: str,
    payload: RegistryServerVersionUpdate,
    *,
    updated_by_user_id: UUID | None = None,
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
    if updated_by_user_id is not None:
        version.updated_by_user_id = updated_by_user_id
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
        if updated_by_user_id is not None:
            server.updated_by_user_id = updated_by_user_id
        await repository.sync_server_categories(session, server.id, category_values(payload))

    await session.flush()
    await session.refresh(version)
    await session.refresh(server)
    trust = await build_trust_context(session, servers=[server], versions=[version])
    return RegistryServerVersionDetailResponse(
        server=server_summary(server, version if version.is_latest else None, trust=trust),
        version=version_summary(version, trust=trust),
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


async def delete_server(session, name: str) -> None:
    server = await repository.get_server(session, name, include_deleted=True)
    if server is None:
        raise RegistryServerNotFoundError("server not found")
    if server.status == "deleted":
        return

    now = datetime.now(UTC)
    versions = await repository.list_server_versions(
        session,
        name,
        include_deleted=True,
    )
    for version in versions:
        version.status = "deleted"
        version.status_message = "Deleted from Wardn Hub."
        version.is_latest = False
        version.status_changed_at = now

    server.status = "deleted"
    server.status_message = "All versions deleted from Wardn Hub."
    server.current_version_id = None
    await repository.sync_server_categories(session, server.id, [])
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
    await repository.sync_server_categories(
        session,
        server.id,
        category_values_from_server_json(version.server_json),
    )
    await session.flush()
    await session.refresh(version)
    await session.refresh(server)
    trust = await build_trust_context(session, servers=[server], versions=[version])
    return RegistryServerVersionDetailResponse(
        server=server_summary(server, version, trust=trust),
        version=version_summary(version, trust=trust),
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
    category: str | None = None,
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
        category=category,
        status=status,
    )
    return RegistryServerListResponse(
        servers=[await server_with_latest(session, server) for server in servers],
        metadata=RegistryListMetadata(count=len(servers), next_cursor=next_cursor),
    )


async def list_categories(session) -> RegistryCategoryListResponse:
    categories = await repository.list_categories(session)
    return RegistryCategoryListResponse(
        categories=[category_summary(category) for category in categories]
    )


async def create_category(
    session,
    payload: RegistryCategoryCreate,
) -> RegistryCategoryRead:
    slug = category_slug(payload.slug)
    existing = await repository.get_category_by_slug(session, slug, include_deleted=True)
    if existing is not None:
        raise DuplicateRegistryCategoryError("category slug already exists")

    existing_orders = await repository.list_category_sort_orders(session)
    category = await repository.create_category(
        session,
        slug=slug,
        name=payload.name.strip(),
        description=payload.description.strip(),
        sort_order=next_category_sort_order(existing_orders, payload.sort_order),
    )
    return category_summary(category)


async def update_category(
    session,
    category_slug_value: str,
    payload: RegistryCategoryUpdate,
) -> RegistryCategoryRead:
    current_slug = category_slug(category_slug_value)
    category = await repository.get_category_by_slug(session, current_slug)
    if category is None:
        raise RegistryCategoryNotFoundError("category not found")

    next_slug = category_slug(payload.slug) if payload.slug is not None else None
    if next_slug is not None and next_slug != current_slug:
        existing = await repository.get_category_by_slug(session, next_slug, include_deleted=True)
        if existing is not None:
            raise DuplicateRegistryCategoryError("category slug already exists")

    sort_order = None
    if payload.sort_order is not None:
        existing_orders = await repository.list_category_sort_orders(
            session,
            exclude_category_id=category.id,
        )
        sort_order = next_category_sort_order(existing_orders, payload.sort_order)

    category = await repository.update_category(
        session,
        category,
        slug=next_slug,
        name=payload.name.strip() if payload.name is not None else None,
        description=payload.description.strip() if payload.description is not None else None,
        sort_order=sort_order,
    )
    return category_summary(category)


async def delete_category(session, category_slug_value: str) -> None:
    slug = category_slug(category_slug_value)
    category = await repository.get_category_by_slug(session, slug)
    if category is None:
        raise RegistryCategoryNotFoundError("category not found")
    await repository.delete_category(session, category)


async def list_registry_users(session) -> RegistryUserListResponse:
    users = await repository.list_public_registry_users(session)
    return RegistryUserListResponse(users=[public_user_summary(user) for user in users])


async def get_registry_user_detail(
    session,
    user_id: UUID,
    *,
    cursor: str | None,
    limit: int,
) -> RegistryUserDetailResponse:
    user = (await repository.list_users_by_ids(session, {user_id})).get(user_id)
    if user is None or not user.is_active:
        raise UserNotFoundError("user not found")

    offset = parse_cursor(cursor)
    servers, next_cursor = await repository.list_servers_for_user(
        session,
        user_id,
        offset=offset,
        limit=limit,
    )
    return RegistryUserDetailResponse(
        user=public_user_summary(user),
        servers=[await server_with_latest(session, server) for server in servers],
        metadata=RegistryListMetadata(count=len(servers), next_cursor=next_cursor),
    )


async def seed_default_categories(session) -> RegistryCategoryListResponse:
    categories = await repository.seed_categories(session, MCP_SERVERS_CATEGORY_SEEDS)
    return RegistryCategoryListResponse(
        categories=[category_summary(category) for category in categories]
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
    trust = await build_trust_context(session, servers=[server], versions=versions)
    return RegistryServerDetailResponse(
        server=server_summary(server, latest, trust=trust),
        versions=[version_summary(version, trust=trust) for version in versions],
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
    trust = await build_trust_context(session, versions=versions)
    return RegistryServerVersionListResponse(
        versions=[version_summary(version, trust=trust) for version in versions],
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
    trust = await build_trust_context(
        session,
        servers=[server],
        versions=[candidate for candidate in (version, latest) if candidate is not None],
    )
    support = partner_support_summary(version.name, trust)
    return RegistryServerVersionDetailResponse(
        server=server_summary(server, latest, trust=trust),
        version=version_summary(version, trust=trust),
        support={"partnerSupport": [item.model_dump(by_alias=True) for item in support]},
    )
