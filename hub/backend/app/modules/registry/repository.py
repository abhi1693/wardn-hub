from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organizations.models import Organization
from app.modules.partners.models import OrganizationServerSupport
from app.modules.registry.category_seed import CategorySeed
from app.modules.registry.models import (
    RegistryCategory,
    RegistryServer,
    RegistryServerCategory,
    RegistryServerVersion,
)
from app.modules.users.models import User


def category_name_from_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.split("-") if part) or "Other"


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
    category: str | None = None,
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
    if category:
        statement = (
            statement.join(
                RegistryServerCategory,
                RegistryServerCategory.server_id == RegistryServer.id,
            )
            .join(RegistryCategory, RegistryCategory.id == RegistryServerCategory.category_id)
            .where(
                RegistryCategory.status == "active",
                or_(
                    RegistryCategory.slug == category,
                    RegistryCategory.name.ilike(category),
                ),
            )
        )

    if version and version != "latest":
        statement = statement.join(
            RegistryServerVersion,
            RegistryServerVersion.server_id == RegistryServer.id,
        ).where(RegistryServerVersion.version == version)

    if support_level or partner is not None:
        support_exists_query = (
            select(OrganizationServerSupport.id)
            .join(
                Organization,
                Organization.id == OrganizationServerSupport.organization_id,
            )
            .where(
                OrganizationServerSupport.server_name == RegistryServer.name,
                OrganizationServerSupport.support_status == "active",
                Organization.is_partner.is_(True),
                Organization.partner_status == "active",
            )
        )
        if support_level:
            support_exists_query = support_exists_query.where(
                OrganizationServerSupport.support_level == support_level
            )
        support_exists = support_exists_query.exists()
        owner_partner_query = select(Organization.id).where(
            Organization.id == RegistryServer.owner_organization_id,
            Organization.is_partner.is_(True),
            Organization.partner_status == "active",
        )
        if support_level:
            owner_partner_query = owner_partner_query.where(
                Organization.partner_support_level == support_level
            )
        owner_partner_exists = owner_partner_query.exists()
        has_partner_support = or_(support_exists, owner_partner_exists)
        statement = statement.where(
            has_partner_support if partner is not False else ~has_partner_support
        )

    # Registry target filters require JSONB path semantics; keep them as no-ops
    # until the registry query layer gets explicit package/remote indexes.
    _ = registry_type, transport_type

    statement = statement.order_by(RegistryServer.name.asc())
    result = await session.execute(statement.offset(offset).limit(limit + 1))
    rows = list(result.scalars().unique().all())
    next_cursor = str(offset + limit) if len(rows) > limit else ""
    return rows[:limit], next_cursor


async def list_published_servers(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
) -> tuple[list[tuple[RegistryServer, RegistryServerVersion]], int]:
    filters = (
        RegistryServer.status == "active",
        RegistryServer.visibility == "public",
        RegistryServer.current_version_id.is_not(None),
        RegistryServerVersion.status == "active",
        RegistryServerVersion.is_latest.is_(True),
    )
    join_condition = and_(
        RegistryServerVersion.id == RegistryServer.current_version_id,
        RegistryServerVersion.server_id == RegistryServer.id,
    )

    total = await session.scalar(
        select(func.count())
        .select_from(RegistryServer)
        .join(RegistryServerVersion, join_condition)
        .where(*filters)
    )
    result = await session.execute(
        select(RegistryServer, RegistryServerVersion)
        .join(RegistryServerVersion, join_condition)
        .where(*filters)
        .order_by(RegistryServer.name.asc())
        .offset(offset)
        .limit(limit)
    )
    return [(server, version) for server, version in result.all()], total or 0


async def list_published_versions_for_servers(
    session: AsyncSession,
    server_ids: set[UUID],
) -> dict[UUID, list[RegistryServerVersion]]:
    if not server_ids:
        return {}
    result = await session.execute(
        select(RegistryServerVersion)
        .where(
            RegistryServerVersion.server_id.in_(server_ids),
            RegistryServerVersion.status == "active",
        )
        .order_by(
            RegistryServerVersion.server_id.asc(),
            RegistryServerVersion.is_latest.desc(),
            RegistryServerVersion.published_at.desc(),
            RegistryServerVersion.version.desc(),
        )
    )
    versions_by_server: dict[UUID, list[RegistryServerVersion]] = {}
    for version in result.scalars().all():
        versions_by_server.setdefault(version.server_id, []).append(version)
    return versions_by_server


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


async def list_users_by_ids(session: AsyncSession, user_ids: set[UUID]) -> dict[UUID, User]:
    if not user_ids:
        return {}
    result = await session.execute(select(User).where(User.id.in_(user_ids)))
    return {user.id: user for user in result.scalars().all()}


async def list_public_registry_users(session: AsyncSession) -> list[User]:
    server_owner_ids = (
        select(RegistryServer.owner_user_id)
        .where(
            RegistryServer.status == "active",
            RegistryServer.current_version_id.is_not(None),
            RegistryServer.owner_user_id.is_not(None),
        )
    )
    version_user_ids = (
        select(RegistryServerVersion.publisher_user_id)
        .join(RegistryServer, RegistryServer.id == RegistryServerVersion.server_id)
        .where(
            RegistryServer.status == "active",
            RegistryServerVersion.status == "active",
            RegistryServerVersion.is_latest.is_(True),
            RegistryServerVersion.publisher_user_id.is_not(None),
        )
    )
    result = await session.execute(
        select(User)
        .where(
            User.is_active.is_(True),
            or_(
                User.id.in_(server_owner_ids),
                User.id.in_(version_user_ids),
            ),
        )
        .order_by(User.first_name.asc(), User.last_name.asc(), User.email.asc())
    )
    return list(result.scalars().unique().all())


async def list_servers_for_user(
    session: AsyncSession,
    user_id: UUID,
    *,
    offset: int,
    limit: int,
) -> tuple[list[RegistryServer], str]:
    statement = (
        visible_servers_query(False)
        .join(
            RegistryServerVersion,
            RegistryServerVersion.id == RegistryServer.current_version_id,
        )
        .where(
            RegistryServer.status == "active",
            RegistryServerVersion.status == "active",
            or_(
                RegistryServer.owner_user_id == user_id,
                RegistryServer.created_by_user_id == user_id,
                RegistryServer.updated_by_user_id == user_id,
                RegistryServerVersion.owner_user_id == user_id,
                RegistryServerVersion.created_by_user_id == user_id,
                RegistryServerVersion.updated_by_user_id == user_id,
                RegistryServerVersion.publisher_user_id == user_id,
            ),
        )
        .order_by(RegistryServer.name.asc())
    )
    result = await session.execute(statement.offset(offset).limit(limit + 1))
    rows = list(result.scalars().unique().all())
    next_cursor = str(offset + limit) if len(rows) > limit else ""
    return rows[:limit], next_cursor


async def list_organizations_by_ids(
    session: AsyncSession,
    organization_ids: set[UUID],
) -> dict[UUID, Organization]:
    if not organization_ids:
        return {}
    result = await session.execute(
        select(Organization).where(Organization.id.in_(organization_ids))
    )
    return {organization.id: organization for organization in result.scalars().all()}


async def list_partner_support_for_servers(
    session: AsyncSession,
    server_names: set[str],
) -> dict[str, list[tuple[OrganizationServerSupport, Organization]]]:
    if not server_names:
        return {}
    result = await session.execute(
        select(OrganizationServerSupport, Organization)
        .join(Organization, Organization.id == OrganizationServerSupport.organization_id)
        .where(
            OrganizationServerSupport.server_name.in_(server_names),
            OrganizationServerSupport.support_status == "active",
            Organization.is_partner.is_(True),
            Organization.partner_status == "active",
        )
        .order_by(
            OrganizationServerSupport.server_name.asc(),
            OrganizationServerSupport.support_level.asc(),
            Organization.name.asc(),
        )
    )
    support_by_server: dict[str, list[tuple[OrganizationServerSupport, Organization]]] = {}
    for support, organization in result.all():
        support_by_server.setdefault(support.server_name, []).append((support, organization))
    return support_by_server


async def list_categories(session: AsyncSession) -> list[RegistryCategory]:
    result = await session.execute(
        select(RegistryCategory)
        .where(RegistryCategory.status == "active")
        .order_by(RegistryCategory.sort_order.asc(), RegistryCategory.name.asc())
    )
    return list(result.scalars().all())


async def get_category_by_slug(
    session: AsyncSession,
    slug: str,
    *,
    include_deleted: bool = False,
) -> RegistryCategory | None:
    statement = select(RegistryCategory).where(RegistryCategory.slug == slug)
    if not include_deleted:
        statement = statement.where(RegistryCategory.status == "active")
    return await session.scalar(statement)


async def list_category_sort_orders(
    session: AsyncSession,
    *,
    exclude_category_id: UUID | None = None,
) -> list[int]:
    statement = select(RegistryCategory.sort_order).where(RegistryCategory.status == "active")
    if exclude_category_id is not None:
        statement = statement.where(RegistryCategory.id != exclude_category_id)
    result = await session.execute(statement)
    return list(result.scalars().all())


async def create_category(
    session: AsyncSession,
    *,
    slug: str,
    name: str,
    description: str,
    sort_order: int,
) -> RegistryCategory:
    category = RegistryCategory(
        slug=slug,
        name=name,
        description=description,
        sort_order=sort_order,
        status="active",
    )
    session.add(category)
    await session.flush()
    await session.refresh(category)
    return category


async def update_category(
    session: AsyncSession,
    category: RegistryCategory,
    *,
    slug: str | None = None,
    name: str | None = None,
    description: str | None = None,
    sort_order: int | None = None,
) -> RegistryCategory:
    if slug is not None:
        category.slug = slug
    if name is not None:
        category.name = name
    if description is not None:
        category.description = description
    if sort_order is not None:
        category.sort_order = sort_order
    await session.flush()
    await session.refresh(category)
    return category


async def delete_category(session: AsyncSession, category: RegistryCategory) -> None:
    await session.execute(
        delete(RegistryServerCategory).where(RegistryServerCategory.category_id == category.id)
    )
    await session.delete(category)
    await session.flush()


async def seed_categories(
    session: AsyncSession,
    category_seeds: tuple[CategorySeed, ...],
) -> list[RegistryCategory]:
    if not category_seeds:
        return []

    result = await session.execute(
        select(RegistryCategory).where(
            RegistryCategory.slug.in_([category.slug for category in category_seeds])
        )
    )
    categories_by_slug = {category.slug: category for category in result.scalars().all()}

    for category_seed in category_seeds:
        category = categories_by_slug.get(category_seed.slug)
        if category is None:
            category = RegistryCategory(
                slug=category_seed.slug,
                name=category_seed.name,
                description=category_seed.description,
                sort_order=category_seed.sort_order,
                status="active",
            )
            session.add(category)
            categories_by_slug[category_seed.slug] = category
        else:
            category.name = category_seed.name
            category.description = category_seed.description
            category.sort_order = category_seed.sort_order
            category.status = "active"

    await session.flush()
    return [categories_by_slug[category.slug] for category in category_seeds]


async def list_categories_for_servers(
    session: AsyncSession,
    server_ids: set[UUID],
) -> dict[UUID, list[RegistryCategory]]:
    if not server_ids:
        return {}
    result = await session.execute(
        select(RegistryServerCategory.server_id, RegistryCategory)
        .join(RegistryCategory, RegistryCategory.id == RegistryServerCategory.category_id)
        .where(
            RegistryServerCategory.server_id.in_(server_ids),
            RegistryCategory.status == "active",
        )
        .order_by(
            RegistryServerCategory.server_id.asc(),
            RegistryCategory.sort_order.asc(),
            RegistryCategory.name.asc(),
        )
    )
    categories_by_server: dict[UUID, list[RegistryCategory]] = {}
    for server_id, category in result.all():
        categories_by_server.setdefault(server_id, []).append(category)
    return categories_by_server


async def list_categories_by_slugs(
    session: AsyncSession,
    slugs: set[str],
) -> dict[str, RegistryCategory]:
    if not slugs:
        return {}
    result = await session.execute(
        select(RegistryCategory).where(
            RegistryCategory.slug.in_(slugs),
            RegistryCategory.status == "active",
        )
    )
    return {category.slug: category for category in result.scalars().all()}


async def sync_server_categories(
    session: AsyncSession,
    server_id: UUID,
    category_slugs: list[str],
) -> None:
    await session.execute(
        delete(RegistryServerCategory).where(RegistryServerCategory.server_id == server_id)
    )
    if not category_slugs:
        return

    result = await session.execute(
        select(RegistryCategory).where(
            RegistryCategory.slug.in_(category_slugs),
            RegistryCategory.status == "active",
        )
    )
    categories_by_slug = {category.slug: category for category in result.scalars().all()}
    created_missing = False
    for slug in category_slugs:
        if slug not in categories_by_slug:
            category = RegistryCategory(
                slug=slug,
                name=category_name_from_slug(slug),
                description="",
                sort_order=1000,
                status="active",
            )
            session.add(category)
            categories_by_slug[slug] = category
            created_missing = True

    if created_missing:
        await session.flush()

    for slug in category_slugs:
        category = categories_by_slug.get(slug)
        if category is not None:
            session.add(
                RegistryServerCategory(
                    server_id=server_id,
                    category_id=category.id,
                    source="metadata",
                )
            )
