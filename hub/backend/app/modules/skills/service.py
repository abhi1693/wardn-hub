import base64
import binascii
import hashlib
import json
import math
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
    audit_results: dict[uuid.UUID, repository.CurrentSkillAudit] | None = None,
    official_owner_keys: set[tuple[str, str]] | None = None,
) -> SkillRead:
    audit = (audit_results or {}).get(skill.id)
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
        auditStatus=audit.status if audit else None,
        auditScore=audit.score if audit else None,
        auditRank=audit.rank if audit else None,
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
    audit_enabled = get_settings().skill_audit_enabled
    if view not in VALID_SKILL_VIEWS:
        raise ValueError("view must be one of all-time, trending, or hot")
    normalized_audit_status = audit_status.strip().lower() if audit_status else None
    if normalized_audit_status and normalized_audit_status not in VALID_SKILL_AUDIT_FILTERS:
        raise ValueError("audit_status must be one of pass, warn, fail, or unaudited")
    if not audit_enabled:
        normalized_audit_status = None
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
    audit_results = await repository.current_skill_audits(session, skills) if audit_enabled else {}
    return SkillListResponse(
        data=[
            skill_read(
                skill,
                audit_results=audit_results,
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
        auditEnabled=audit_enabled,
    )


async def search_skills(
    session: AsyncSession,
    *,
    query: str,
    limit: int = 50,
    owner: str | None = None,
    audit_status: str | None = None,
    official: bool | None = None,
    cursor: str | None = None,
) -> SkillSearchResponse:
    audit_enabled = get_settings().skill_audit_enabled
    search_query = query.strip()
    normalized_audit_status = audit_status.strip().lower() if audit_status else None
    if normalized_audit_status and normalized_audit_status not in VALID_SKILL_AUDIT_FILTERS:
        raise ValueError("audit_status must be one of pass, warn, fail, or unaudited")
    if not audit_enabled:
        normalized_audit_status = None
    cursor_fingerprint = skill_search_cursor_fingerprint(
        query=search_query,
        owner=owner,
        audit_status=normalized_audit_status,
        official=official,
    )
    decoded_cursor = decode_skill_search_cursor(cursor, cursor_fingerprint) if cursor else None
    started_at = perf_counter()
    page = await repository.search_skill_documents(
        session,
        query=search_query,
        limit=limit,
        owner=owner,
        audit_status=normalized_audit_status,
        official=official,
        cursor=decoded_cursor,
    )
    skills = page.skills
    official_keys = await repository.official_owner_keys(session, skills)
    audit_results = await repository.current_skill_audits(session, skills) if audit_enabled else {}
    return SkillSearchResponse(
        data=[
            skill_read(
                skill,
                audit_results=audit_results,
                official_owner_keys=official_keys,
            )
            for skill in skills
        ],
        query=search_query,
        searchType="lexical",
        count=len(skills),
        hasMore=page.has_more,
        nextCursor=(
            encode_skill_search_cursor(page.next_cursor, cursor_fingerprint)
            if page.next_cursor
            else None
        ),
        durationMs=max(0, int((perf_counter() - started_at) * 1000)),
        auditEnabled=audit_enabled,
    )


def skill_search_cursor_fingerprint(
    *,
    query: str,
    owner: str | None,
    audit_status: str | None,
    official: bool | None,
) -> str:
    material = json.dumps(
        {
            "auditStatus": audit_status or "",
            "official": official,
            "owner": (owner or "").strip().casefold(),
            "query": query.strip().casefold(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def encode_skill_search_cursor(
    cursor: repository.SkillSearchCursor,
    fingerprint: str,
) -> str:
    payload = {
        "f": fingerprint,
        "i": cursor.installs,
        "id": str(cursor.skill_id),
        "n": cursor.name,
        "r": cursor.text_rank.hex(),
        "s": cursor.source,
        "t": cursor.match_tier,
        "v": 1,
        "z": cursor.trigram_rank.hex(),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return encoded.decode("ascii").rstrip("=")


def decode_skill_search_cursor(
    value: str,
    expected_fingerprint: str,
) -> repository.SkillSearchCursor:
    if not value or len(value) > 2048:
        raise ValueError("search cursor is invalid")
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.b64decode(value + padding, altchars=b"-_", validate=True))
        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("f") != expected_fingerprint
        ):
            raise ValueError
        cursor = repository.SkillSearchCursor(
            match_tier=int(payload["t"]),
            text_rank=float.fromhex(payload["r"]),
            trigram_rank=float.fromhex(payload["z"]),
            installs=int(payload["i"]),
            name=str(payload["n"]),
            source=str(payload["s"]),
            skill_id=uuid.UUID(payload["id"]),
        )
    except (binascii.Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("search cursor is invalid") from exc
    if (
        cursor.match_tier not in range(5)
        or cursor.installs < 0
        or not math.isfinite(cursor.text_rank)
        or not math.isfinite(cursor.trigram_rank)
        or not cursor.name
        or not cursor.source
    ):
        raise ValueError("search cursor is invalid")
    return cursor


async def get_skill_detail(
    session: AsyncSession,
    skill_id: str,
    *,
    include_bundle: bool = False,
) -> SkillDetailResponse:
    audit_enabled = get_settings().skill_audit_enabled
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
            bundleFormatVersion=None,
            sourceCommitSha=None,
            sourceEntrypoint=None,
            resolutionStatus=None,
            resolutionIssues=[],
            auditEnabled=audit_enabled,
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
        bundleFormatVersion=snapshot.bundle_format_version,
        sourceCommitSha=snapshot.source_commit_sha or None,
        sourceEntrypoint=snapshot.source_entrypoint,
        resolutionStatus=snapshot.resolution_status,
        resolutionIssues=snapshot.resolution_issues or [],
        auditEnabled=audit_enabled,
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
    if (
        snapshot is None
        or snapshot.content_hash != content_hash
        or snapshot.bundle_format_version != 2
        or snapshot.resolution_status != "complete"
    ):
        raise SkillNotFoundError("skill snapshot not found")
    await repository.record_install_event(
        session,
        skill=skill,
        snapshot=snapshot,
        source=client,
        resolver_version=resolver_version,
    )


def audit_read(audit: SkillAudit) -> SkillAuditRead:
    categories = list(
        dict.fromkeys(
            str(finding.get("category", ""))
            for finding in (audit.findings or [])
            if finding.get("category")
        )
    )
    return SkillAuditRead(
        scannerName=audit.scanner_name,
        scannerVersion=audit.scanner_version,
        policyName=audit.policy_name,
        policyVersion=audit.policy_version,
        policyFingerprint=audit.policy_fingerprint,
        status=audit.status,
        summary=audit.summary,
        auditedAt=audit.audited_at,
        riskLevel=audit.risk_level,
        score=audit.score,
        rank=audit.rank,
        scoreDeductions=audit.score_deductions or [],
        categories=categories or None,
        findings=audit.findings or [],
        analyzers=audit.analyzers or [],
        scanDurationMs=audit.scan_duration_ms,
    )


async def get_skill_audit(session: AsyncSession, skill_id: str) -> SkillAuditResponse:
    if not get_settings().skill_audit_enabled:
        raise SkillAuditNotFoundError("skill audits are disabled")
    source, slug = split_skill_id(skill_id)
    skill = await repository.get_skill(session, source, slug)
    if skill is None:
        raise SkillNotFoundError("skill not found")
    audit = await repository.get_current_skill_audit(session, skill)
    if audit is None:
        raise SkillAuditNotFoundError("skill audits not found")
    return SkillAuditResponse(
        id=f"{skill.source}/{skill.slug}",
        source=skill.source,
        slug=skill.slug,
        contentHash=audit.content_hash,
        audit=audit_read(audit),
    )


async def list_official_skills(session: AsyncSession) -> SkillOfficialResponse:
    audit_enabled = get_settings().skill_audit_enabled
    skills, _total = await repository.list_skills(
        session,
        offset=0,
        limit=500,
        view="all-time",
        official=True,
    )
    official_keys = await repository.official_owner_keys(session, skills)
    audit_results = await repository.current_skill_audits(session, skills) if audit_enabled else {}
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
                        audit_results=audit_results,
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
        auditEnabled=audit_enabled,
    )
