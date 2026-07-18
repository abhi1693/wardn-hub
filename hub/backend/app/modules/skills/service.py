import uuid
from collections import defaultdict
from datetime import UTC, datetime
from time import perf_counter

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli.skills import (
    DEFAULT_IMPORT_TIMEOUT_SECONDS,
    GitHubClient,
    GitHubSystemicError,
    SkillCliError,
    discover_skill_paths,
    github_token_from_args,
    import_skill_from_github_path,
    parse_github_repository_url,
    save_imported_repository,
    skill_bundle_tree_items,
    validate_import_subfolder,
    validate_unique_imported_skill_slugs,
)
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
    SkillGitHubImportResponse,
    SkillListResponse,
    SkillOfficialResponse,
    SkillPagination,
    SkillRead,
    SkillSearchResponse,
)

VALID_SKILL_VIEWS = {"all-time", "trending", "hot"}
VALID_SKILL_AUDIT_FILTERS = {"pass", "warn", "fail", "unaudited"}


class SkillGitHubImportError(ValueError):
    pass


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


def github_import_subfolder_from_url_path(path: str) -> str:
    normalized = path.strip().strip("/")
    if not normalized:
        return ""
    if normalized == "SKILL.md":
        return ""
    if normalized.endswith("/SKILL.md"):
        normalized = normalized[: -len("/SKILL.md")]
    return validate_import_subfolder(normalized) if normalized else ""


async def import_github_skill_request(
    repository_url: str,
) -> SkillGitHubImportResponse:
    try:
        repo = parse_github_repository_url(repository_url)
        subfolder = github_import_subfolder_from_url_path(repo.path)
    except SkillCliError as exc:
        raise SkillGitHubImportError(str(exc)) from exc

    try:
        async with GitHubClient(
            token=github_token_from_args(None),
            timeout_seconds=DEFAULT_IMPORT_TIMEOUT_SECONDS,
        ) as client:
            metadata = await client.repository_metadata(repo)
            if not metadata.default_branch:
                raise SkillGitHubImportError("GitHub repository has no default branch")
            requested_ref = repo.ref or metadata.default_branch
            resolved_ref = await client.resolve_commit_sha(repo, requested_ref)
            tree = await client.recursive_tree(repo, resolved_ref)
            skill_paths = discover_skill_paths(tree, recursive=True, subfolder=subfolder)
            imported = []
            for skill_path in skill_paths:
                bundle_items = skill_bundle_tree_items(tree, skill_path=skill_path)
                imported.append(
                    await import_skill_from_github_path(
                        client=client,
                        repo=repo,
                        ref=requested_ref,
                        tree=tree,
                        skill_path=skill_path,
                        fetch_ref=resolved_ref,
                        owner_avatar_url=metadata.owner_avatar_url,
                        import_subfolder=subfolder,
                        bundle_items=bundle_items,
                    )
                )
            validate_unique_imported_skill_slugs(imported)
            results = await save_imported_repository(imported)
    except (SkillCliError, GitHubSystemicError) as exc:
        raise SkillGitHubImportError(str(exc)) from exc
    except httpx.RequestError as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise SkillGitHubImportError(f"GitHub request failed: {detail}") from exc

    skill_ids = [f"{skill.source}/{skill.slug}" for skill, _snapshot, _source_path in results]
    return SkillGitHubImportResponse(
        source=repo.source,
        importedSkillCount=len(skill_ids),
        skillIds=skill_ids,
    )


def official_owner_key(skill: Skill) -> tuple[str, str]:
    return (skill.source_type, owner_from_skill(skill).lower())


def skill_read(
    skill: Skill,
    *,
    audit_statuses: dict[uuid.UUID, str] | None = None,
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
        installs=skill.installs,
        isOfficial=official_owner_key(skill) in (official_owner_keys or set()),
        isDuplicate=True if skill.is_duplicate else None,
        auditStatus=(audit_statuses or {}).get(skill.id),
    )


async def list_skills(
    session: AsyncSession,
    *,
    view: str = "all-time",
    audit_status: str | None = None,
    page: int = 0,
    per_page: int = 100,
    query: str | None = None,
    owner: str | None = None,
    source: str | None = None,
    official: bool | None = None,
) -> SkillListResponse:
    if view not in VALID_SKILL_VIEWS:
        raise ValueError("view must be one of all-time, trending, or hot")
    normalized_audit_status = audit_status.strip().lower() if audit_status else None
    if normalized_audit_status and normalized_audit_status not in VALID_SKILL_AUDIT_FILTERS:
        raise ValueError("audit_status must be one of pass, warn, fail, or unaudited")
    offset = page * per_page
    search_query = query.strip() if query else None
    skills, total = await repository.list_skills(
        session,
        offset=offset,
        limit=per_page,
        view=view,
        audit_status=normalized_audit_status,
        search=search_query,
        owner=owner,
        source=source,
        official=official,
    )
    official_keys = await repository.official_owner_keys(session, skills)
    audit_statuses = await repository.current_skill_audit_statuses(session, skills)
    return SkillListResponse(
        data=[
            skill_read(
                skill,
                audit_statuses=audit_statuses,
                official_owner_keys=official_keys,
            )
            for skill in skills
        ],
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
    audit_statuses = await repository.current_skill_audit_statuses(session, skills)
    return SkillSearchResponse(
        data=[
            skill_read(
                skill,
                audit_statuses=audit_statuses,
                official_owner_keys=official_keys,
            )
            for skill in skills
        ],
        query=search_query,
        searchType="semantic" if " " in search_query else "fuzzy",
        count=len(skills),
        durationMs=max(0, int((perf_counter() - started_at) * 1000)),
    )


async def get_skill_detail(
    session: AsyncSession,
    skill_id: str,
    *,
    include_bundle: bool = False,
) -> SkillDetailResponse:
    source, slug = split_skill_id(skill_id)
    skill = await repository.get_skill(session, source, slug)
    if skill is None:
        raise SkillNotFoundError("skill not found")
    snapshot = await repository.get_skill_snapshot(
        session,
        skill,
        include_files=include_bundle,
    )
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
    snapshot_files = (
        snapshot.files or []
        if include_bundle
        else [{"path": "SKILL.md", "contents": snapshot.skill_md}]
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
        files=[SkillFileRead.model_validate(file) for file in snapshot_files],
    )


async def record_skill_install(
    session: AsyncSession,
    skill_id: str,
    *,
    content_hash: str,
    resolver_version: str,
    client: str = "find-skills",
) -> None:
    source, slug = split_skill_id(skill_id)
    skill = await repository.get_skill(session, source, slug)
    if skill is None:
        raise SkillNotFoundError("skill not found")
    snapshot = await repository.get_skill_snapshot(session, skill, include_files=False)
    if snapshot is None or snapshot.content_hash != content_hash:
        raise SkillNotFoundError("skill snapshot not found")
    await repository.record_install_event(
        session,
        skill=skill,
        snapshot=snapshot,
        source=client,
        resolver_version=resolver_version,
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
        contentHash=audits[0].content_hash,
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
    audit_statuses = await repository.current_skill_audit_statuses(session, skills)
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
                    skill_read(
                        skill,
                        audit_statuses=audit_statuses,
                        official_owner_keys=official_keys,
                    )
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
