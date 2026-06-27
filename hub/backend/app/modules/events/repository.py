import uuid
from datetime import datetime

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import EventDelivery, EventRecord, EventRule
from app.modules.organizations.models import OrganizationMembership


def visible_rules_statement(user_id: uuid.UUID, *, include_all: bool = False) -> Select:
    statement = select(EventRule).order_by(EventRule.created_at.desc())
    if include_all:
        return statement
    organization_ids = select(OrganizationMembership.organization_id).where(
        OrganizationMembership.user_id == user_id,
        OrganizationMembership.is_active.is_(True),
    )
    return statement.where(
        or_(
            EventRule.owner_user_id == user_id,
            EventRule.owner_organization_id.in_(organization_ids),
        )
    )


async def list_event_rules(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    include_all: bool = False,
) -> list[EventRule]:
    result = await session.execute(visible_rules_statement(user_id, include_all=include_all))
    return list(result.scalars().all())


async def get_event_rule_by_id(session: AsyncSession, rule_id: uuid.UUID) -> EventRule | None:
    return await session.get(EventRule, rule_id)


async def delete_event_rule(session: AsyncSession, rule: EventRule) -> None:
    await session.delete(rule)


async def list_enabled_rules_for_event_type(
    session: AsyncSession,
    event_type: str,
) -> list[EventRule]:
    result = await session.execute(
        select(EventRule)
        .where(EventRule.is_enabled.is_(True), EventRule.event_types.contains([event_type]))
        .order_by(EventRule.created_at.asc())
    )
    return list(result.scalars().all())


async def list_unprocessed_event_records(
    session: AsyncSession,
    *,
    limit: int,
) -> list[EventRecord]:
    result = await session.execute(
        select(EventRecord)
        .where(EventRecord.processed_at.is_(None))
        .order_by(EventRecord.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_event_record_by_id(session: AsyncSession, event_id: uuid.UUID) -> EventRecord | None:
    return await session.get(EventRecord, event_id)


def visible_deliveries_statement(user_id: uuid.UUID, *, include_all: bool = False) -> Select:
    statement = select(EventDelivery).join(
        EventRule,
        EventDelivery.event_rule_id == EventRule.id,
        isouter=True,
    )
    return visible_deliveries_scope_statement(statement, user_id, include_all=include_all)


def visible_deliveries_scope_statement(
    statement: Select,
    user_id: uuid.UUID,
    *,
    include_all: bool = False,
) -> Select:
    if include_all:
        return statement.order_by(EventDelivery.created_at.desc())
    organization_ids = select(OrganizationMembership.organization_id).where(
        OrganizationMembership.user_id == user_id,
        OrganizationMembership.is_active.is_(True),
    )
    return (
        statement.where(
            or_(
                EventRule.owner_user_id == user_id,
                EventRule.owner_organization_id.in_(organization_ids),
            )
        )
        .order_by(EventDelivery.created_at.desc())
    )


async def list_event_deliveries(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    include_all: bool = False,
    rule_id: uuid.UUID | None = None,
    limit: int,
) -> list[EventDelivery]:
    statement = visible_deliveries_statement(user_id, include_all=include_all)
    if rule_id is not None:
        statement = statement.where(EventDelivery.event_rule_id == rule_id)
    result = await session.execute(
        statement.limit(limit)
    )
    return list(result.scalars().all())


async def list_due_event_deliveries(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int,
) -> list[EventDelivery]:
    result = await session.execute(
        select(EventDelivery)
        .where(
            EventDelivery.status.in_(["pending", "retrying"]),
            or_(EventDelivery.next_attempt_at.is_(None), EventDelivery.next_attempt_at <= now),
        )
        .order_by(EventDelivery.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_event_delivery_by_id(
    session: AsyncSession,
    delivery_id: uuid.UUID,
) -> EventDelivery | None:
    return await session.get(EventDelivery, delivery_id)
