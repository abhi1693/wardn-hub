import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, String, and_, case, cast, exists, func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, load_only

from app.modules.skills.models import (
    Skill,
    SkillAudit,
    SkillInstallEvent,
    SkillSnapshot,
    SkillSourceOwner,
)


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


def canonical_skill_condition():
    """Keep the strongest listing for each non-empty install location.

    Ranking all candidates once avoids the correlated anti-join that otherwise
    scans every skill from the same source once for every catalog row.
    """
    candidate = aliased(Skill)
    install_location = case(
        (candidate.install_url != "", candidate.install_url),
        else_=cast(candidate.id, String),
    )
    ranked_candidates = (
        select(
            candidate.id.label("skill_id"),
            func.row_number()
            .over(
                partition_by=(
                    candidate.source_type,
                    candidate.source,
                    install_location,
                ),
                order_by=(
                    candidate.installs.desc(),
                    func.length(candidate.slug),
                    candidate.slug,
                ),
            )
            .label("canonical_rank"),
        )
        .where(
            candidate.status == "active",
            candidate.visibility == "public",
            candidate.current_snapshot_id.is_not(None),
        )
        .subquery()
    )
    return Skill.id.in_(
        select(ranked_candidates.c.skill_id).where(
            ranked_candidates.c.canonical_rank == 1
        )
    )


def wardn_find_skills_order():
    return case(
        (
            and_(
                func.lower(Skill.source_name) == "wardn-hub",
                func.lower(Skill.name) == "find-skills",
            ),
            0,
        ),
        else_=1,
    )


def current_skill_audit_status_subquery():
    ranked_audits = (
        select(
            SkillAudit.skill_id.label("skill_id"),
            SkillAudit.slug.label("slug"),
            SkillAudit.status.label("status"),
        )
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
            SkillSnapshot.status == "active",
            SkillSnapshot.is_latest.is_(True),
        )
        .cte("ranked_current_skill_audits")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )
    status_weight = case(
        (ranked_audits.c.status == "fail", 2),
        (ranked_audits.c.status == "warn", 1),
        (ranked_audits.c.status == "pass", 0),
    )
    worst_statuses = (
        select(
            ranked_audits.c.skill_id.label("skill_id"),
            func.max(status_weight).label("status_weight"),
        )
        .where(ranked_audits.c.audit_rank == 1)
        .where(ranked_audits.c.status.in_(("pass", "warn", "fail")))
        .group_by(ranked_audits.c.skill_id)
        .cte("current_skill_audit_weights")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )
    return (
        select(
            worst_statuses.c.skill_id.label("skill_id"),
            case(
                (worst_statuses.c.status_weight == 2, "fail"),
                (worst_statuses.c.status_weight == 1, "warn"),
                else_="pass",
            ).label("audit_status"),
        )
        .subquery()
    )


def apply_audit_status_filter(statement: Select, audit_status: str) -> Select:
    current_audit_statuses = current_skill_audit_status_subquery()
    audited_skill_ids = select(current_audit_statuses.c.skill_id)
    if audit_status == "unaudited":
        return statement.where(Skill.id.not_in(audited_skill_ids))
    return statement.where(
        Skill.id.in_(
            audited_skill_ids.where(
                current_audit_statuses.c.audit_status == audit_status
            )
        )
    )


async def list_skills(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    view: str = "all-time",
    audit_status: str | None = None,
    search: str | None = None,
    owner: str | None = None,
    source: str | None = None,
    official: bool | None = None,
) -> tuple[list[Skill], int]:
    statement = published_skill_query(Skill)
    total_statement = published_skill_query(func.count())
    canonical_condition = canonical_skill_condition()
    statement = statement.where(canonical_condition)
    total_statement = total_statement.where(canonical_condition)

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

    if audit_status:
        statement = apply_audit_status_filter(statement, audit_status)
        total_statement = apply_audit_status_filter(total_statement, audit_status)

    if view == "all-time":
        statement = statement.order_by(
            wardn_find_skills_order(),
            Skill.installs.desc(),
            Skill.name.asc(),
            Skill.source.asc(),
        )
    elif view in {"trending", "hot"}:
        window = timedelta(days=7) if view == "trending" else timedelta(hours=24)
        recent_installs = (
            select(
                SkillInstallEvent.skill_id,
                func.count(SkillInstallEvent.id).label("recent_installs"),
            )
            .where(SkillInstallEvent.created_at >= datetime.now(UTC) - window)
            .group_by(SkillInstallEvent.skill_id)
            .subquery()
        )
        statement = statement.outerjoin(
            recent_installs,
            recent_installs.c.skill_id == Skill.id,
        ).order_by(
            wardn_find_skills_order(),
            func.coalesce(recent_installs.c.recent_installs, 0).desc(),
            Skill.installs.desc(),
            Skill.name.asc(),
            Skill.source.asc(),
        )
    else:
        statement = statement.order_by(wardn_find_skills_order(), Skill.name.asc())

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


async def record_install_event(
    session: AsyncSession,
    *,
    skill: Skill,
    snapshot: SkillSnapshot,
    source: str,
    resolver_version: str,
) -> None:
    session.add(
        SkillInstallEvent(
            skill_id=skill.id,
            snapshot_id=snapshot.id,
            content_hash=snapshot.content_hash or "",
            source=source,
            resolver_version=resolver_version,
        )
    )
    await session.execute(
        update(Skill)
        .where(Skill.id == skill.id)
        .values(installs=Skill.installs + 1)
    )
    await session.commit()


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
