import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organizations.models import Organization
from app.modules.partners.models import OrganizationServerSupport


async def list_partner_organizations(session: AsyncSession) -> list[Organization]:
    result = await session.execute(
        select(Organization)
        .where(
            Organization.is_partner.is_(True),
            Organization.partner_status != "ended",
        )
        .order_by(Organization.name.asc())
    )
    return list(result.scalars().all())


async def get_support_by_id(
    session: AsyncSession,
    support_id: uuid.UUID,
) -> OrganizationServerSupport | None:
    return await session.get(OrganizationServerSupport, support_id)


async def get_support_by_organization_and_server(
    session: AsyncSession,
    organization_id: uuid.UUID,
    server_name: str,
) -> OrganizationServerSupport | None:
    result = await session.execute(
        select(OrganizationServerSupport).where(
            OrganizationServerSupport.organization_id == organization_id,
            OrganizationServerSupport.server_name == server_name,
        )
    )
    return result.scalar_one_or_none()


async def list_support_for_organization(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> list[OrganizationServerSupport]:
    result = await session.execute(
        select(OrganizationServerSupport)
        .where(OrganizationServerSupport.organization_id == organization_id)
        .order_by(OrganizationServerSupport.server_name.asc())
    )
    return list(result.scalars().all())
