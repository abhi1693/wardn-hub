import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.namespaces.models import NamespaceClaim

ACTIVE_NAMESPACE_STATUSES = {"pending", "verified"}


async def get_claim_by_id(
    session: AsyncSession,
    claim_id: uuid.UUID,
) -> NamespaceClaim | None:
    return await session.get(NamespaceClaim, claim_id)


async def get_active_claim_by_namespace(
    session: AsyncSession,
    namespace: str,
) -> NamespaceClaim | None:
    result = await session.execute(
        select(NamespaceClaim).where(
            NamespaceClaim.namespace == namespace,
            NamespaceClaim.status.in_(ACTIVE_NAMESPACE_STATUSES),
        )
    )
    return result.scalar_one_or_none()


async def list_claims(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    organization_ids: list[uuid.UUID] | None = None,
    include_all: bool = False,
) -> list[NamespaceClaim]:
    statement = select(NamespaceClaim).order_by(
        NamespaceClaim.created_at.desc(),
        NamespaceClaim.id.desc(),
    )
    if not include_all and user_id is not None:
        filters = [NamespaceClaim.claimed_by_user_id == user_id]
        if organization_ids:
            filters.append(NamespaceClaim.owner_organization_id.in_(organization_ids))
        statement = statement.where(or_(*filters))
    result = await session.execute(statement)
    return list(result.scalars().all())
