from collections import defaultdict
from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.skills import repository
from app.modules.skills.exceptions import SkillAuditNotFoundError, SkillNotFoundError
from app.modules.skills.models import Skill, SkillAudit
from app.modules.skills.schemas import (
    OfficialSkillOwner,
    SkillAuditRead,
    SkillAuditResponse,
    SkillDetailResponse,
    SkillFileRead,
    SkillListResponse,
    SkillOfficialResponse,
    SkillPagination,
    SkillRead,
    SkillSearchResponse,
)

VALID_SKILL_VIEWS = {"all-time", "trending", "hot"}


def split_skill_id(skill_id: str) -> tuple[str, str]:
    parts = [part.strip() for part in skill_id.strip("/").split("/") if part.strip()]
    if len(parts) < 2:
        raise SkillNotFoundError("skill not found")
    return "/".join(parts[:-1]), parts[-1]


def owner_from_skill(skill: Skill) -> str:
    if skill.source_owner:
        return skill.source_owner
    return skill.source.split("/", 1)[0] if "/" in skill.source else skill.source


def name_from_skill(skill: Skill) -> str:
    if skill.source_name:
        return skill.source_name
    return skill.source.split("/", 1)[1] if "/" in skill.source else skill.source


def skill_url(skill: Skill) -> str:
    base_url = get_settings().registry_public_base_url.rstrip("/")
    return f"{base_url}/skills/{skill.source}/{skill.slug}"


def official_owner_key(skill: Skill) -> tuple[str, str]:
    return (skill.source_type, owner_from_skill(skill).lower())


def skill_read(
    skill: Skill,
    *,
    official_owner_keys: set[tuple[str, str]] | None = None,
) -> SkillRead:
    return SkillRead(
        id=f"{skill.source}/{skill.slug}",
        slug=skill.slug,
        name=skill.name,
        source=skill.source,
        sourceType=skill.source_type,
        sourceOwner=owner_from_skill(skill),
        sourceName=name_from_skill(skill),
        sourceOwnerUrl=skill.source_owner_url or None,
        sourceOwnerIconUrl=skill.source_owner_icon_url or None,
        sourceUrl=skill.source_url or None,
        installUrl=skill.install_url or None,
        url=skill_url(skill),
        description=skill.description,
        isOfficial=official_owner_key(skill) in (official_owner_keys or set()),
        isDuplicate=True if skill.is_duplicate else None,
    )


async def list_skills(
    session: AsyncSession,
    *,
    view: str = "all-time",
    page: int = 0,
    per_page: int = 100,
    query: str | None = None,
    owner: str | None = None,
    source: str | None = None,
    official: bool | None = None,
) -> SkillListResponse:
    if view not in VALID_SKILL_VIEWS:
        raise ValueError("view must be one of all-time, trending, or hot")
    offset = page * per_page
    search_query = query.strip() if query else None
    skills, total = await repository.list_skills(
        session,
        offset=offset,
        limit=per_page,
        view=view,
        search=search_query,
        owner=owner,
        source=source,
        official=official,
    )
    official_keys = await repository.official_owner_keys(session, skills)
    return SkillListResponse(
        data=[skill_read(skill, official_owner_keys=official_keys) for skill in skills],
        pagination=SkillPagination(
            page=page,
            perPage=per_page,
            total=total,
            hasMore=offset + len(skills) < total,
        ),
    )


async def search_skills(
    session: AsyncSession,
    *,
    query: str,
    limit: int = 50,
    owner: str | None = None,
) -> SkillSearchResponse:
    search_query = query.strip()
    started_at = perf_counter()
    skills, _total = await repository.list_skills(
        session,
        offset=0,
        limit=limit,
        view="all-time",
        search=search_query,
        owner=owner,
    )
    official_keys = await repository.official_owner_keys(session, skills)
    return SkillSearchResponse(
        data=[skill_read(skill, official_owner_keys=official_keys) for skill in skills],
        query=search_query,
        searchType="semantic" if " " in search_query else "fuzzy",
        count=len(skills),
        durationMs=max(0, int((perf_counter() - started_at) * 1000)),
    )


async def get_skill_detail(session: AsyncSession, skill_id: str) -> SkillDetailResponse:
    source, slug = split_skill_id(skill_id)
    skill = await repository.get_skill(session, source, slug)
    if skill is None:
        raise SkillNotFoundError("skill not found")
    snapshot = await repository.get_skill_snapshot(session, skill)
    if snapshot is None:
        return SkillDetailResponse(
            id=f"{skill.source}/{skill.slug}",
            source=skill.source,
            slug=skill.slug,
            sourceOwner=owner_from_skill(skill),
            sourceName=name_from_skill(skill),
            sourceOwnerUrl=skill.source_owner_url or None,
            sourceOwnerIconUrl=skill.source_owner_icon_url or None,
            sourceUrl=skill.source_url or None,
            hash=None,
            files=None,
        )
    return SkillDetailResponse(
        id=f"{skill.source}/{skill.slug}",
        source=skill.source,
        slug=skill.slug,
        sourceOwner=owner_from_skill(skill),
        sourceName=name_from_skill(skill),
        sourceOwnerUrl=skill.source_owner_url or None,
        sourceOwnerIconUrl=skill.source_owner_icon_url or None,
        sourceUrl=skill.source_url or None,
        hash=snapshot.content_hash,
        files=[
            SkillFileRead.model_validate(file)
            for file in snapshot.files
            if file.get("path") == "SKILL.md"
        ],
    )


def audit_read(audit: SkillAudit) -> SkillAuditRead:
    return SkillAuditRead(
        provider=audit.provider,
        slug=audit.slug,
        status=audit.status,
        summary=audit.summary,
        auditedAt=audit.audited_at,
        riskLevel=audit.risk_level or None,
        categories=audit.categories or None,
    )


async def get_skill_audit(session: AsyncSession, skill_id: str) -> SkillAuditResponse:
    source, slug = split_skill_id(skill_id)
    skill = await repository.get_skill(session, source, slug)
    if skill is None:
        raise SkillNotFoundError("skill not found")
    audits = await repository.list_skill_audits(session, skill)
    if not audits:
        raise SkillAuditNotFoundError("skill audits not found")
    return SkillAuditResponse(
        id=f"{skill.source}/{skill.slug}",
        source=skill.source,
        slug=skill.slug,
        audits=[audit_read(audit) for audit in audits],
    )


async def list_official_skills(session: AsyncSession) -> SkillOfficialResponse:
    skills, _total = await repository.list_skills(
        session,
        offset=0,
        limit=500,
        view="all-time",
        official=True,
    )
    official_keys = await repository.official_owner_keys(session, skills)
    groups: dict[str, list[Skill]] = defaultdict(list)
    for skill in skills:
        groups[owner_from_skill(skill)].append(skill)

    owners = []
    for owner, owner_skills in sorted(groups.items()):
        featured = sorted(owner_skills, key=lambda skill: (skill.source, skill.name))[0]
        owners.append(
            OfficialSkillOwner(
                owner=owner,
                sourceOwnerIconUrl=featured.source_owner_icon_url or None,
                ownerUrl=featured.source_owner_url or None,
                featuredRepo=name_from_skill(featured),
                featuredSkill=featured.name,
                skills=[
                    skill_read(skill, official_owner_keys=official_keys)
                    for skill in owner_skills
                ],
            )
        )
    return SkillOfficialResponse(
        data=owners,
        totalOwners=len(owners),
        totalSkills=sum(len(owner.skills) for owner in owners),
        generatedAt=datetime.now(UTC),
    )
