from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import ByteCache, cache_key
from app.core.router import bad_request, not_found
from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.skills.exceptions import SkillAuditNotFoundError, SkillNotFoundError
from app.modules.skills.schemas import (
    SkillAuditResponse,
    SkillDetailResponse,
    SkillGitHubImportRequest,
    SkillGitHubImportResponse,
    SkillListResponse,
    SkillOfficialResponse,
    SkillSearchResponse,
)
from app.modules.skills.service import (
    get_skill_audit,
    get_skill_detail,
    import_github_skill_request,
    list_official_skills,
    list_skills,
    record_skill_install,
    search_skills,
)

router = APIRouter(prefix="/skills", tags=["skills"])
SKILL_SEARCH_CACHE_VERSION = 1


@router.get("", response_model=SkillListResponse, operation_id="skills_list")
async def list_skill_catalog(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    view: str = "all-time",
    audit_status: Annotated[
        str | None,
        Query(
            description="Filter by current audit status: pass, warn, fail, or unaudited.",
        ),
    ] = None,
    page: Annotated[int, Query(ge=0)] = 0,
    per_page: Annotated[int, Query(ge=1, le=500)] = 100,
    q: str | None = None,
    owner: str | None = None,
    source: str | None = None,
    official: bool | None = None,
) -> SkillListResponse:
    try:
        return await list_skills(
            session,
            view=view,
            audit_status=audit_status,
            page=page,
            per_page=per_page,
            query=q,
            owner=owner,
            source=source,
            official=official,
        )
    except ValueError as exc:
        raise bad_request(exc, detail=str(exc)) from exc


@router.get("/search", response_model=SkillSearchResponse, operation_id="skills_search")
async def search_skill_catalog(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    q: Annotated[str, Query(min_length=3, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    owner: str | None = None,
    audit_status: Annotated[
        str | None,
        Query(description="Filter by current audit status: pass, warn, fail, or unaudited."),
    ] = None,
    official: bool | None = None,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> Response:
    cache = cast(ByteCache | None, getattr(request.app.state, "cache", None))
    key = cache_key(
        "skill-search",
        version=SKILL_SEARCH_CACHE_VERSION,
        material={
            "auditEnabled": request.app.state.settings.skill_audit_enabled,
            "auditStatus": (audit_status or "").strip().lower(),
            "cursor": cursor or "",
            "limit": limit,
            "official": official,
            "owner": (owner or "").strip().casefold(),
            "query": q.strip().casefold(),
        },
    )
    if cache is not None:
        cached = await cache.get(key)
        if cached is not None:
            return Response(
                content=cached,
                media_type="application/json",
                headers={"X-Cache": "HIT"},
            )
    try:
        result = await search_skills(
            session,
            query=q,
            limit=limit,
            owner=owner,
            audit_status=audit_status,
            official=official,
            cursor=cursor,
        )
    except ValueError as exc:
        raise bad_request(exc, detail=str(exc)) from exc
    body = result.model_dump_json(by_alias=True).encode("utf-8")
    if cache is not None:
        await cache.set(key, body)
    return Response(
        content=body,
        media_type="application/json",
        headers={"X-Cache": "MISS" if cache is not None else "BYPASS"},
    )


@router.get("/official", response_model=SkillOfficialResponse, operation_id="skills_official")
async def list_official_skill_catalog(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SkillOfficialResponse:
    return await list_official_skills(session)


@router.post(
    "/import-github",
    response_model=SkillGitHubImportResponse,
    operation_id="skills_import_github",
    responses={status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse}},
)
async def import_github_skill_catalog(
    payload: SkillGitHubImportRequest,
) -> SkillGitHubImportResponse:
    try:
        return await import_github_skill_request(payload.repository_url)
    except ValueError as exc:
        raise bad_request(exc, detail=str(exc)) from exc


@router.get(
    "/audit/{skill_id:path}",
    response_model=SkillAuditResponse,
    operation_id="skills_audit_get",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_skill_catalog_audit(
    skill_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SkillAuditResponse:
    try:
        return await get_skill_audit(session, skill_id)
    except (SkillNotFoundError, SkillAuditNotFoundError) as exc:
        raise not_found(exc, detail=str(exc)) from exc


@router.post(
    "/telemetry/{skill_id:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="skills_install_telemetry",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def record_skill_install_telemetry(
    skill_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    content_hash: Annotated[str, Query(pattern=r"^[a-f0-9]{64}$")],
    resolver_version: Annotated[
        str,
        Query(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$"),
    ] = "unknown",
    client: Annotated[
        str,
        Query(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$"),
    ] = "find-skills",
) -> Response:
    try:
        await record_skill_install(
            session,
            skill_id,
            content_hash=content_hash,
            resolver_version=resolver_version,
            client=client,
        )
    except SkillNotFoundError as exc:
        raise not_found(exc, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{skill_id:path}",
    response_model=SkillDetailResponse,
    operation_id="skills_get",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_skill_catalog_detail(
    skill_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    include_bundle: Annotated[
        bool,
        Query(description="Include scripts, references, assets, and other stored skill files."),
    ] = False,
) -> SkillDetailResponse:
    try:
        return await get_skill_detail(session, skill_id, include_bundle=include_bundle)
    except SkillNotFoundError as exc:
        raise not_found(exc, detail="skill not found") from exc
