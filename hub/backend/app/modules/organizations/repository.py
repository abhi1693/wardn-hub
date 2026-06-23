import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.organizations.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
)


async def list_organizations_for_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    include_archived: bool = False,
) -> list[tuple[Organization, OrganizationMembership | None]]:
    statement = (
        select(Organization, OrganizationMembership)
        .outerjoin(
            OrganizationMembership,
            and_(
                OrganizationMembership.organization_id == Organization.id,
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.is_active.is_(True),
            ),
        )
        .options(selectinload(OrganizationMembership.role))
        .order_by(Organization.name.asc())
    )
    if not include_archived:
        statement = statement.where(Organization.status != "archived")
    result = await session.execute(statement)
    return list(result.all())


async def list_joined_organizations_for_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    include_archived: bool = False,
) -> list[tuple[Organization, OrganizationMembership]]:
    statement = (
        select(Organization, OrganizationMembership)
        .join(OrganizationMembership, OrganizationMembership.organization_id == Organization.id)
        .where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.is_active.is_(True),
        )
        .options(selectinload(OrganizationMembership.role))
        .order_by(Organization.name.asc())
    )
    if not include_archived:
        statement = statement.where(Organization.status != "archived")
    result = await session.execute(statement)
    return list(result.all())


async def get_organization_by_id(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> Organization | None:
    return await session.get(Organization, organization_id)


async def get_organization_by_slug(session: AsyncSession, slug: str) -> Organization | None:
    result = await session.execute(select(Organization).where(Organization.slug == slug))
    return result.scalar_one_or_none()


async def get_organization_role_by_slug(
    session: AsyncSession,
    organization_id: uuid.UUID,
    slug: str,
) -> OrganizationRole | None:
    result = await session.execute(
        select(OrganizationRole).where(
            OrganizationRole.organization_id == organization_id,
            OrganizationRole.slug == slug,
        )
    )
    return result.scalar_one_or_none()


async def list_organization_roles(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> list[OrganizationRole]:
    result = await session.execute(
        select(OrganizationRole)
        .where(OrganizationRole.organization_id == organization_id)
        .order_by(OrganizationRole.is_system_role.desc(), OrganizationRole.slug.asc())
    )
    return list(result.scalars().all())


async def get_organization_membership(
    session: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> OrganizationMembership | None:
    result = await session.execute(
        select(OrganizationMembership)
        .options(selectinload(OrganizationMembership.role))
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_any_organization_membership(
    session: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> OrganizationMembership | None:
    result = await session.execute(
        select(OrganizationMembership)
        .options(selectinload(OrganizationMembership.role))
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_organization_memberships(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> list[OrganizationMembership]:
    result = await session.execute(
        select(OrganizationMembership)
        .options(selectinload(OrganizationMembership.role))
        .where(OrganizationMembership.organization_id == organization_id)
        .order_by(OrganizationMembership.created_at.asc())
    )
    return list(result.scalars().all())

