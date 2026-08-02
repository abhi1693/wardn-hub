import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import (
    Select,
    String,
    and_,
    case,
    cast,
    delete,
    exists,
    func,
    literal,
    or_,
    select,
    tuple_,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, load_only
from sqlalchemy.sql.elements import ColumnElement

from app.modules.registry.models import RegistryCategory
from app.modules.skills.models import (
    Skill,
    SkillAudit,
    SkillCategory,
    SkillInstallEvent,
    SkillSearchDocument,
    SkillSnapshot,
    SkillSourceOwner,
)

_SEARCH_FALLBACK_MAX_TERMS = 8
_SEARCH_FALLBACK_MIN_TERMS = 3
_SEARCH_FALLBACK_STOP_WORDS = {
    "a",
    "an",
    "and",
    "find",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "skill",
    "skills",
    "the",
    "to",
    "use",
    "using",
    "with",
}


@dataclass(frozen=True)
class CurrentSkillAudit:
    status: str
    score: int
    rank: str


@dataclass(frozen=True)
class SkillCategorizationTarget:
    skill_id: uuid.UUID
    source: str
    slug: str
    name: str
    description: str
    skill_md: str

    @property
    def catalog_id(self) -> str:
        return f"{self.source}/{self.slug}"


@dataclass(frozen=True)
class SkillAuditHistoryItem:
    content_hash: str
    source_commit_sha: str
    published_at: datetime
    audited_at: datetime
    status: str
    risk_level: str
    score: int
    rank: str
    snapshot_id: uuid.UUID


@dataclass(frozen=True)
class SkillSearchCursor:
    match_tier: int
    text_rank: float
    trigram_rank: float
    installs: int
    name: str
    source: str
    skill_id: uuid.UUID


@dataclass(frozen=True)
class SkillSearchPage:
    skills: list[Skill]
    has_more: bool
    next_cursor: SkillSearchCursor | None


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
            audited_skill_condition(Skill.id),
        )
    )


def official_owner_condition(
    source_type=Skill.source_type,
    source_owner=Skill.source_owner,
):
    return exists(
        select(SkillSourceOwner.id).where(
            SkillSourceOwner.source_type == source_type,
            func.lower(SkillSourceOwner.source_owner) == func.lower(source_owner),
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


def skill_search_fallback_query(search: str) -> str | None:
    terms = list(
        dict.fromkeys(
            term
            for term in re.findall(r"[a-z0-9]+", search.casefold())
            if len(term) >= 2 and term not in _SEARCH_FALLBACK_STOP_WORDS
        )
    )
    if len(terms) < _SEARCH_FALLBACK_MIN_TERMS:
        return None
    return " OR ".join(terms[:_SEARCH_FALLBACK_MAX_TERMS])


def current_skill_audit_status_subquery():
    # Audit configuration is retained as provenance. Public eligibility follows
    # the current immutable snapshot so provider/model changes do not hide results.
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
            SkillSnapshot.bundle_format_version == 2,
            SkillSnapshot.resolution_status == "complete",
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


def audit_status_condition(skill_id, audit_status: str):
    current_audit_statuses = current_skill_audit_status_subquery()
    audited_skill_ids = select(current_audit_statuses.c.skill_id)
    if audit_status == "unaudited":
        return skill_id.not_in(audited_skill_ids)
    return skill_id.in_(
        audited_skill_ids.where(current_audit_statuses.c.audit_status == audit_status)
    )


def audited_skill_condition(skill_id):
    current_audit_statuses = current_skill_audit_status_subquery()
    return skill_id.in_(select(current_audit_statuses.c.skill_id))


def category_filter_condition(category: str, skill_id=Skill.id):
    category_value = category.strip()
    return exists(
        select(SkillCategory.id)
        .join(RegistryCategory, RegistryCategory.id == SkillCategory.category_id)
        .where(
            SkillCategory.skill_id == skill_id,
            RegistryCategory.status == "active",
            or_(
                RegistryCategory.slug == category_value,
                RegistryCategory.name.ilike(category_value),
            ),
        )
    )


def _search_after_condition(
    cursor: SkillSearchCursor,
    *,
    match_tier,
    text_rank,
    trigram_rank,
    name_order,
    source_order,
):
    columns = (
        (match_tier, cursor.match_tier, "asc"),
        (text_rank, cursor.text_rank, "desc"),
        (trigram_rank, cursor.trigram_rank, "desc"),
        (SkillSearchDocument.installs, cursor.installs, "desc"),
        (name_order, cursor.name, "asc"),
        (source_order, cursor.source, "asc"),
        (SkillSearchDocument.skill_id, cursor.skill_id, "asc"),
    )
    conditions = []
    equal_prefix = []
    for column, value, direction in columns:
        comparison = column > value if direction == "asc" else column < value
        conditions.append(and_(*equal_prefix, comparison))
        equal_prefix.append(column == value)
    return or_(*conditions)


async def search_skill_documents(
    session: AsyncSession,
    *,
    query: str,
    limit: int,
    owner: str | None = None,
    category: str | None = None,
    official: bool | None = None,
    audit_status: str | None = None,
    cursor: SkillSearchCursor | None = None,
) -> SkillSearchPage:
    normalized_query = query.strip().casefold()
    escaped_query = normalized_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    english_query = func.websearch_to_tsquery("english", query)
    simple_query = func.websearch_to_tsquery("simple", query)
    english_match = SkillSearchDocument.search_vector.op("@@")(english_query)
    simple_match = SkillSearchDocument.search_vector.op("@@")(simple_query)
    fallback_query = skill_search_fallback_query(query)
    if fallback_query is None:
        fallback_english_query = None
        fallback_simple_query = None
        fallback_match = literal(False)
        fallback_rank = literal(0.0)
    else:
        fallback_english_query = func.websearch_to_tsquery("english", fallback_query)
        fallback_simple_query = func.websearch_to_tsquery("simple", fallback_query)
        fallback_english_match = SkillSearchDocument.search_vector.op("@@")(
            fallback_english_query
        )
        fallback_simple_match = SkillSearchDocument.search_vector.op("@@")(
            fallback_simple_query
        )
        fallback_match = or_(fallback_english_match, fallback_simple_match)
        fallback_rank = (
            func.ts_rank_cd(
                SkillSearchDocument.search_vector,
                fallback_english_query,
                32,
            )
            + func.ts_rank_cd(
                SkillSearchDocument.search_vector,
                fallback_simple_query,
                32,
            )
        )
    identifier_parts = skill_identifier_parts(normalized_query)
    exact_full_id = (
        and_(
            func.lower(SkillSearchDocument.source) == identifier_parts[0].casefold(),
            func.lower(SkillSearchDocument.slug) == identifier_parts[1].casefold(),
        )
        if identifier_parts is not None
        else literal(False)
    )
    normalized_name = func.lower(SkillSearchDocument.name)
    normalized_slug = func.lower(SkillSearchDocument.slug)
    prefix_pattern = f"{escaped_query}%"
    exact_name = normalized_name == normalized_query
    exact_slug = normalized_slug == normalized_query
    prefix_match = or_(
        normalized_name.ilike(prefix_pattern, escape="\\"),
        normalized_slug.ilike(prefix_pattern, escape="\\"),
    )
    trigram_match = SkillSearchDocument.identity_text.op("%")(normalized_query)
    contains_match = SkillSearchDocument.identity_text.ilike(
        f"%{escaped_query}%",
        escape="\\",
    )
    text_match = or_(english_match, simple_match)
    match_tier = case(
        (exact_full_id, 0),
        (or_(exact_name, exact_slug), 1),
        (prefix_match, 2),
        (text_match, 3),
        (fallback_match, 4),
        else_=5,
    ).label("match_tier")
    text_rank = (
        func.ts_rank_cd(SkillSearchDocument.search_vector, english_query, 32)
        + func.ts_rank_cd(SkillSearchDocument.search_vector, simple_query, 32)
        + fallback_rank
    ).label("text_rank")
    trigram_rank = func.greatest(
        func.similarity(SkillSearchDocument.identity_text, normalized_query),
        func.word_similarity(normalized_query, SkillSearchDocument.identity_text),
    ).label("trigram_rank")
    name_order = normalized_name.label("name_order")
    source_order = func.lower(SkillSearchDocument.source).label("source_order")
    statement = select(
        SkillSearchDocument.skill_id,
        match_tier,
        text_rank,
        trigram_rank,
        SkillSearchDocument.installs,
        name_order,
        source_order,
    ).where(
        SkillSearchDocument.is_canonical.is_(True),
        audited_skill_condition(SkillSearchDocument.skill_id),
        or_(
            exact_full_id,
            text_match,
            fallback_match,
            trigram_match,
            contains_match,
        ),
    )
    if owner:
        owner_value = owner.strip()
        statement = statement.where(
            or_(
                func.lower(SkillSearchDocument.source_owner) == owner_value.casefold(),
                SkillSearchDocument.source.ilike(f"{owner_value}/%"),
            )
        )
    if category:
        statement = statement.where(
            category_filter_condition(category, SkillSearchDocument.skill_id)
        )
    if official is not None:
        condition = official_owner_condition(
            SkillSearchDocument.source_type,
            SkillSearchDocument.source_owner,
        )
        statement = statement.where(condition if official else ~condition)
    if audit_status:
        statement = statement.where(
            audit_status_condition(SkillSearchDocument.skill_id, audit_status)
        )
    if cursor is not None:
        statement = statement.where(
            _search_after_condition(
                cursor,
                match_tier=match_tier,
                text_rank=text_rank,
                trigram_rank=trigram_rank,
                name_order=name_order,
                source_order=source_order,
            )
        )
    statement = statement.order_by(
        match_tier,
        text_rank.desc(),
        trigram_rank.desc(),
        SkillSearchDocument.installs.desc(),
        name_order,
        source_order,
        SkillSearchDocument.skill_id,
    ).limit(limit + 1)
    candidates = statement.subquery()
    result = await session.execute(
        select(
            Skill,
            candidates.c.match_tier,
            candidates.c.text_rank,
            candidates.c.trigram_rank,
            candidates.c.installs,
            candidates.c.name_order,
            candidates.c.source_order,
        )
        .join(candidates, candidates.c.skill_id == Skill.id)
        .order_by(
            candidates.c.match_tier,
            candidates.c.text_rank.desc(),
            candidates.c.trigram_rank.desc(),
            candidates.c.installs.desc(),
            candidates.c.name_order,
            candidates.c.source_order,
            candidates.c.skill_id,
        )
    )
    rows = result.all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = SkillSearchCursor(
            match_tier=last.match_tier,
            text_rank=float(last.text_rank),
            trigram_rank=float(last.trigram_rank),
            installs=last.installs,
            name=last.name_order,
            source=last.source_order,
            skill_id=last[0].id,
        )
    return SkillSearchPage(
        skills=[row[0] for row in rows],
        has_more=has_more,
        next_cursor=next_cursor,
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
    category: str | None = None,
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

    if category:
        condition = category_filter_condition(category)
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
    elif view == "latest":
        statement = statement.order_by(
            *identifier_ordering,
            wardn_find_skills_order(),
            SkillSnapshot.published_at.desc(),
            Skill.name.asc(),
            Skill.source.asc(),
        )
    elif view == "oldest":
        statement = statement.order_by(
            *identifier_ordering,
            wardn_find_skills_order(),
            SkillSnapshot.published_at.asc(),
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


async def categories_for_skills(
    session: AsyncSession,
    skills: list[Skill],
) -> dict[uuid.UUID, list[RegistryCategory]]:
    skill_ids = [skill.id for skill in skills]
    if not skill_ids:
        return {}

    result = await session.execute(
        select(SkillCategory.skill_id, RegistryCategory)
        .join(RegistryCategory, RegistryCategory.id == SkillCategory.category_id)
        .where(
            SkillCategory.skill_id.in_(skill_ids),
            RegistryCategory.status == "active",
        )
        .order_by(
            SkillCategory.skill_id,
            RegistryCategory.sort_order.asc(),
            RegistryCategory.name.asc(),
        )
    )
    categories_by_skill: dict[uuid.UUID, list[RegistryCategory]] = {}
    for skill_id, category in result.all():
        categories_by_skill.setdefault(skill_id, []).append(category)
    return categories_by_skill


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
            SkillSnapshot.bundle_format_version == 2,
            SkillSnapshot.resolution_status == "complete",
            SkillAudit.status.in_(("pass", "warn", "fail")),
        )
    )
    return {
        skill_id: CurrentSkillAudit(status=status, score=score, rank=rank)
        for skill_id, status, score, rank in result.all()
    }


async def list_active_categories(session: AsyncSession) -> list[RegistryCategory]:
    result = await session.execute(
        select(RegistryCategory)
        .where(RegistryCategory.status == "active")
        .order_by(RegistryCategory.sort_order.asc(), RegistryCategory.name.asc())
    )
    return list(result.scalars().all())


async def list_skill_categorization_targets(
    session: AsyncSession,
    *,
    limit: int,
    skill_id: str | None = None,
    include_categorized: bool = False,
) -> list[SkillCategorizationTarget]:
    statement = (
        select(
            Skill.id,
            Skill.source,
            Skill.slug,
            Skill.name,
            Skill.description,
            SkillSnapshot.skill_md,
        )
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
            SkillSnapshot.bundle_format_version == 2,
            SkillSnapshot.resolution_status == "complete",
        )
        .order_by(Skill.updated_at.asc(), Skill.id.asc())
        .limit(limit)
    )
    if not include_categorized:
        statement = statement.where(
            ~exists(select(SkillCategory.id).where(SkillCategory.skill_id == Skill.id))
        )
    if skill_id:
        source, separator, slug = skill_id.strip().rpartition("/")
        if not separator or not source or not slug:
            return []
        statement = statement.where(Skill.source == source, Skill.slug == slug)

    result = await session.execute(statement)
    return [SkillCategorizationTarget(*row) for row in result.all()]


async def replace_skill_categories(
    session: AsyncSession,
    *,
    skill_id: uuid.UUID,
    category_slugs: list[str],
    source: str = "llm",
) -> list[RegistryCategory]:
    normalized_slugs = list(dict.fromkeys(slug.strip() for slug in category_slugs if slug.strip()))
    if not normalized_slugs:
        await session.execute(delete(SkillCategory).where(SkillCategory.skill_id == skill_id))
        return []

    result = await session.execute(
        select(RegistryCategory).where(
            RegistryCategory.slug.in_(normalized_slugs),
            RegistryCategory.status == "active",
        )
    )
    categories_by_slug = {category.slug: category for category in result.scalars().all()}
    missing_slugs = [slug for slug in normalized_slugs if slug not in categories_by_slug]
    if missing_slugs:
        raise ValueError(f"unknown category slug: {missing_slugs[0]}")

    await session.execute(delete(SkillCategory).where(SkillCategory.skill_id == skill_id))
    assignments = [
        SkillCategory(
            skill_id=skill_id,
            category_id=categories_by_slug[slug].id,
            source=source,
        )
        for slug in normalized_slugs
    ]
    session.add_all(assignments)
    await session.flush()
    return [categories_by_slug[slug] for slug in normalized_slugs]


async def get_skill(session: AsyncSession, source: str, slug: str) -> Skill | None:
    result = await session.execute(
        published_skill_query(Skill).where(Skill.source == source, Skill.slug == slug)
    )
    return result.scalar_one_or_none()


async def get_skill_snapshot(
    session: AsyncSession,
    skill: Skill,
    *,
    content_hash: str | None = None,
    include_files: bool = True,
) -> SkillSnapshot | None:
    query = select(SkillSnapshot).where(SkillSnapshot.skill_id == skill.id)
    if content_hash is None:
        query = query.where(
            SkillSnapshot.id == skill.current_snapshot_id,
            SkillSnapshot.status == "active",
            SkillSnapshot.is_latest.is_(True),
        )
    else:
        query = query.where(
            SkillSnapshot.content_hash == content_hash,
            SkillSnapshot.status == "active",
            SkillSnapshot.bundle_format_version == 2,
            SkillSnapshot.resolution_status == "complete",
            exists(
                select(SkillAudit.id).where(
                    SkillAudit.skill_id == skill.id,
                    SkillAudit.snapshot_id == SkillSnapshot.id,
                    SkillAudit.content_hash == SkillSnapshot.content_hash,
                    SkillAudit.status.in_(("pass", "warn", "fail")),
                )
            ),
        )
    if not include_files:
        query = query.options(
            load_only(
                SkillSnapshot.content_hash,
                SkillSnapshot.skill_md,
                SkillSnapshot.bundle_format_version,
                SkillSnapshot.source_commit_sha,
                SkillSnapshot.source_entrypoint,
                SkillSnapshot.resolution_status,
                SkillSnapshot.resolution_issues,
            )
        )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_skill_audit_for_snapshot(
    session: AsyncSession,
    skill: Skill,
    *,
    content_hash: str,
) -> SkillAudit | None:
    result = await session.execute(
        select(SkillAudit)
        .join(
            SkillSnapshot,
            and_(
                SkillSnapshot.id == SkillAudit.snapshot_id,
                SkillSnapshot.skill_id == SkillAudit.skill_id,
                SkillSnapshot.content_hash == SkillAudit.content_hash,
            ),
        )
        .where(
            SkillAudit.skill_id == skill.id,
            SkillAudit.content_hash == content_hash,
            SkillSnapshot.status == "active",
            SkillSnapshot.bundle_format_version == 2,
            SkillSnapshot.resolution_status == "complete",
            SkillAudit.status.in_(("pass", "warn", "fail")),
        )
        .limit(1)
    )
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
        .join(
            SkillSnapshot,
            and_(
                SkillSnapshot.id == SkillAudit.snapshot_id,
                SkillSnapshot.skill_id == SkillAudit.skill_id,
                SkillSnapshot.content_hash == SkillAudit.content_hash,
            ),
        )
        .where(
            SkillAudit.skill_id == skill.id,
            SkillAudit.snapshot_id == skill.current_snapshot_id,
            SkillSnapshot.status == "active",
            SkillSnapshot.is_latest.is_(True),
            SkillSnapshot.bundle_format_version == 2,
            SkillSnapshot.resolution_status == "complete",
            SkillAudit.status.in_(("pass", "warn", "fail")),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_skill_audit_history(
    session: AsyncSession,
    skill: Skill,
    *,
    limit: int,
) -> list[SkillAuditHistoryItem]:
    result = await session.execute(
        select(
            SkillAudit.content_hash,
            SkillSnapshot.source_commit_sha,
            SkillSnapshot.published_at,
            SkillAudit.audited_at,
            SkillAudit.status,
            SkillAudit.risk_level,
            SkillAudit.score,
            SkillAudit.rank,
            SkillSnapshot.id,
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
            SkillAudit.skill_id == skill.id,
            SkillSnapshot.bundle_format_version == 2,
            SkillSnapshot.resolution_status == "complete",
            SkillAudit.status.in_(("pass", "warn", "fail")),
        )
        .order_by(
            case((SkillSnapshot.id == skill.current_snapshot_id, 0), else_=1),
            SkillSnapshot.published_at.desc(),
            SkillAudit.audited_at.desc(),
            SkillAudit.id.desc(),
        )
        .limit(limit)
    )
    return [SkillAuditHistoryItem(*row) for row in result.tuples().all()]
