import uuid

from sqlalchemy import Select, and_, exists, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.modules.skills.models import Skill, SkillAudit, SkillSnapshot, SkillSourceOwner


def published_skill_query(*entities) -> Select:
    return (
        select(*entities)
        .select_from(Skill)
        .join(
            SkillSnapshot,
            and_(
                SkillSnapshot.id == Skill.current_snapshot_id,
                SkillSnapshot.skill_id == Skill.id,
            ),
        )
        .where(
            Skill.status == "active",
            Skill.visibility == "public",
            Skill.current_snapshot_id.is_not(None),
            SkillSnapshot.status == "active",
            SkillSnapshot.is_latest.is_(True),
        )
    )


def official_owner_condition():
    return exists(
        select(SkillSourceOwner.id).where(
            SkillSourceOwner.source_type == Skill.source_type,
            func.lower(SkillSourceOwner.source_owner) == func.lower(Skill.source_owner),
            SkillSourceOwner.is_official.is_(True),
        )
    )


async def list_skills(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    view: str = "all-time",
    search: str | None = None,
    owner: str | None = None,
    source: str | None = None,
    official: bool | None = None,
) -> tuple[list[Skill], int]:
    statement = published_skill_query(Skill)
    total_statement = published_skill_query(func.count())

    if search:
        pattern = f"%{search.strip()}%"
        condition = or_(
            Skill.name.ilike(pattern),
            Skill.slug.ilike(pattern),
            Skill.source.ilike(pattern),
            Skill.source_owner.ilike(pattern),
            Skill.source_name.ilike(pattern),
            Skill.description.ilike(pattern),
        )
        statement = statement.where(condition)
        total_statement = total_statement.where(condition)

    if owner:
        owner_value = owner.strip()
        owner_prefix = f"{owner_value}/%"
        condition = or_(
            Skill.source_owner.ilike(owner_value),
            Skill.source.ilike(owner_prefix),
        )
        statement = statement.where(condition)
        total_statement = total_statement.where(condition)

    if source:
        source_value = source.strip()
        statement = statement.where(Skill.source == source_value)
        total_statement = total_statement.where(Skill.source == source_value)

    if official is not None:
        condition = official_owner_condition()
        if not official:
            condition = ~condition
        statement = statement.where(condition)
        total_statement = total_statement.where(condition)

    if view == "all-time":
        statement = statement.order_by(Skill.name.asc(), Skill.source.asc())
    elif view == "trending":
        statement = statement.order_by(Skill.updated_at.desc(), Skill.name.asc())
    elif view == "hot":
        statement = statement.order_by(Skill.updated_at.desc(), Skill.name.asc())
    else:
        statement = statement.order_by(Skill.name.asc())

    total = await session.scalar(total_statement)
    result = await session.execute(statement.offset(offset).limit(limit))
    return list(result.scalars().unique().all()), total or 0


async def official_owner_keys(session: AsyncSession, skills: list[Skill]) -> set[tuple[str, str]]:
    keys = {
        (skill.source_type, skill.source_owner.lower())
        for skill in skills
        if skill.source_type and skill.source_owner
    }
    if not keys:
        return set()

    result = await session.execute(
        select(SkillSourceOwner.source_type, func.lower(SkillSourceOwner.source_owner))
        .where(
            tuple_(
                SkillSourceOwner.source_type,
                func.lower(SkillSourceOwner.source_owner),
            ).in_(keys),
            SkillSourceOwner.is_official.is_(True),
        )
    )
    return {(source_type, source_owner) for source_type, source_owner in result.all()}


async def current_skill_audit_statuses(
    session: AsyncSession,
    skills: list[Skill],
) -> dict[uuid.UUID, str]:
    snapshot_keys = [
        (skill.id, skill.current_snapshot_id)
        for skill in skills
        if skill.current_snapshot_id is not None
    ]
    if not snapshot_keys:
        return {}

    ranked_audits = (
        select(SkillAudit.skill_id, SkillAudit.slug, SkillAudit.status)
        .add_columns(
            func.row_number()
            .over(
                partition_by=(SkillAudit.skill_id, SkillAudit.slug),
                order_by=(SkillAudit.audited_at.desc(), SkillAudit.id.desc()),
            )
            .label("audit_rank")
        )
        .join(
            SkillSnapshot,
            and_(
                SkillSnapshot.id == SkillAudit.snapshot_id,
                SkillSnapshot.skill_id == SkillAudit.skill_id,
                SkillSnapshot.content_hash == SkillAudit.content_hash,
            ),
        )
        .where(
            tuple_(SkillAudit.skill_id, SkillAudit.snapshot_id).in_(snapshot_keys),
            SkillSnapshot.status == "active",
            SkillSnapshot.is_latest.is_(True),
        )
        .subquery()
    )
    result = await session.execute(
        select(ranked_audits.c.skill_id, ranked_audits.c.status).where(
            ranked_audits.c.audit_rank == 1
        )
    )

    status_weight = {"pass": 0, "warn": 1, "fail": 2}
    statuses: dict[uuid.UUID, str] = {}
    for skill_id, status in result.all():
        if status not in status_weight:
            continue
        current = statuses.get(skill_id)
        if current is None or status_weight[status] > status_weight[current]:
            statuses[skill_id] = status
    return statuses


async def get_skill(session: AsyncSession, source: str, slug: str) -> Skill | None:
    result = await session.execute(
        published_skill_query(Skill).where(Skill.source == source, Skill.slug == slug)
    )
    return result.scalar_one_or_none()


async def get_skill_snapshot(
    session: AsyncSession,
    skill: Skill,
    *,
    include_files: bool = True,
) -> SkillSnapshot | None:
    query = select(SkillSnapshot).where(
        SkillSnapshot.id == skill.current_snapshot_id,
        SkillSnapshot.skill_id == skill.id,
        SkillSnapshot.status == "active",
        SkillSnapshot.is_latest.is_(True),
    )
    if not include_files:
        query = query.options(
            load_only(
                SkillSnapshot.content_hash,
                SkillSnapshot.skill_md,
            )
        )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def list_skill_audits(session: AsyncSession, skill: Skill) -> list[SkillAudit]:
    result = await session.execute(
        select(SkillAudit)
        .where(
            SkillAudit.skill_id == skill.id,
            SkillAudit.snapshot_id == skill.current_snapshot_id,
            SkillAudit.content_hash
            == select(SkillSnapshot.content_hash)
            .where(SkillSnapshot.id == skill.current_snapshot_id)
            .scalar_subquery(),
        )
        .order_by(SkillAudit.audited_at.desc(), SkillAudit.provider.asc())
        .limit(32)
    )
    return list(result.scalars().all())
