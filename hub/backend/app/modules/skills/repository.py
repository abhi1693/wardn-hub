import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, String, and_, case, cast, exists, func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, load_only
from sqlalchemy.sql.elements import ColumnElement

from app.modules.skills.audit_policy import current_audit_configuration_hash
from app.modules.skills.models import (
    Skill,
    SkillAudit,
    SkillInstallEvent,
    SkillSnapshot,
    SkillSourceOwner,
)


@dataclass(frozen=True)
class CurrentSkillAudit:
    status: str
    score: int
    rank: str


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

    PostgreSQL can estimate DISTINCT ON cardinality accurately and hash this
    set into the surrounding catalog query. A row_number filter is estimated
    as a tiny result and causes nested-loop rescans under audit-status filters.
    """
    candidate = aliased(Skill)
    install_location = case(
        (candidate.install_url != "", candidate.install_url),
        else_=cast(candidate.id, String),
    )
    canonical_candidates = (
        select(candidate.id.label("skill_id"))
        .where(
            candidate.status == "active",
            candidate.visibility == "public",
            candidate.current_snapshot_id.is_not(None),
        )
        .distinct(
            candidate.source_type,
            candidate.source,
            install_location,
        )
        .order_by(
            candidate.source_type,
            candidate.source,
            install_location,
            candidate.installs.desc(),
            func.length(candidate.slug),
            candidate.slug,
        )
        .subquery()
    )
    return Skill.id.in_(select(canonical_candidates.c.skill_id))


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


def skill_identifier_parts(search: str) -> tuple[str, str] | None:
    source_or_repository, separator, slug = search.strip().rpartition("/")
    if not separator or not source_or_repository or not slug:
        return None
    return source_or_repository, slug


def skill_identifier_condition(search: str) -> ColumnElement[bool] | None:
    parts = skill_identifier_parts(search)
    if parts is None:
        return None
    source_or_repository, slug = parts
    return and_(
        Skill.slug.ilike(slug),
        or_(
            Skill.source.ilike(source_or_repository),
            Skill.source_name.ilike(source_or_repository),
            Skill.source.ilike(f"%/{source_or_repository}"),
        ),
    )


def skill_identifier_order(search: str) -> ColumnElement[int] | None:
    parts = skill_identifier_parts(search)
    if parts is None:
        return None
    source_or_repository, slug = parts
    normalized_source = source_or_repository.casefold()
    normalized_slug = slug.casefold()
    return case(
        (
            and_(
                func.lower(Skill.source) == normalized_source,
                func.lower(Skill.slug) == normalized_slug,
            ),
            0,
        ),
        (
            and_(
                func.lower(Skill.source_name) == normalized_source,
                func.lower(Skill.slug) == normalized_slug,
            ),
            1,
        ),
        else_=2,
    )


def current_skill_audit_status_subquery():
    return (
        select(
            SkillAudit.skill_id.label("skill_id"),
            SkillAudit.status.label("audit_status"),
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
            SkillAudit.configuration_hash == current_audit_configuration_hash(),
            SkillAudit.status.in_(("pass", "warn", "fail")),
        )
        .subquery()
    )


def apply_audit_status_filter(statement: Select, audit_status: str) -> Select:
    current_audit_statuses = current_skill_audit_status_subquery()
    audited_skill_ids = select(current_audit_statuses.c.skill_id)
    if audit_status == "unaudited":
        return statement.where(Skill.id.not_in(audited_skill_ids))
    return statement.where(
        Skill.id.in_(audited_skill_ids.where(current_audit_statuses.c.audit_status == audit_status))
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
        conditions: list[ColumnElement[bool]] = [
            Skill.name.ilike(pattern),
            Skill.slug.ilike(pattern),
            Skill.source.ilike(pattern),
            Skill.source_owner.ilike(pattern),
            Skill.source_name.ilike(pattern),
            Skill.description.ilike(pattern),
        ]
        identifier_condition = skill_identifier_condition(search)
        if identifier_condition is not None:
            conditions.append(identifier_condition)
        condition = or_(*conditions)
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

    identifier_order = skill_identifier_order(search) if search else None
    identifier_ordering = [identifier_order] if identifier_order is not None else []

    if view == "all-time":
        statement = statement.order_by(
            *identifier_ordering,
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
            *identifier_ordering,
            wardn_find_skills_order(),
            func.coalesce(recent_installs.c.recent_installs, 0).desc(),
            Skill.installs.desc(),
            Skill.name.asc(),
            Skill.source.asc(),
        )
    else:
        statement = statement.order_by(
            *identifier_ordering,
            wardn_find_skills_order(),
            Skill.name.asc(),
        )

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
        select(SkillSourceOwner.source_type, func.lower(SkillSourceOwner.source_owner)).where(
            tuple_(
                SkillSourceOwner.source_type,
                func.lower(SkillSourceOwner.source_owner),
            ).in_(keys),
            SkillSourceOwner.is_official.is_(True),
        )
    )
    return {(source_type, source_owner) for source_type, source_owner in result.all()}


async def current_skill_audits(
    session: AsyncSession,
    skills: list[Skill],
) -> dict[uuid.UUID, CurrentSkillAudit]:
    snapshot_keys = [
        (skill.id, skill.current_snapshot_id)
        for skill in skills
        if skill.current_snapshot_id is not None
    ]
    if not snapshot_keys:
        return {}

    result = await session.execute(
        select(SkillAudit.skill_id, SkillAudit.status, SkillAudit.score, SkillAudit.rank)
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
            SkillAudit.configuration_hash == current_audit_configuration_hash(),
            SkillAudit.status.in_(("pass", "warn", "fail")),
        )
    )
    return {
        skill_id: CurrentSkillAudit(status=status, score=score, rank=rank)
        for skill_id, status, score, rank in result.all()
    }


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
        update(Skill).where(Skill.id == skill.id).values(installs=Skill.installs + 1)
    )
    await session.commit()


async def get_current_skill_audit(
    session: AsyncSession,
    skill: Skill,
) -> SkillAudit | None:
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
        .where(SkillAudit.configuration_hash == current_audit_configuration_hash())
        .limit(1)
    )
    return result.scalar_one_or_none()
