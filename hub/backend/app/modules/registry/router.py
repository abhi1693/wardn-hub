from datetime import datetime
from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.router import (
    bad_request,
    commit_response,
    commit_session,
    conflict,
    forbidden,
    not_found,
)
from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.registry.exceptions import (
    DuplicateRegistryCategoryError,
    DuplicateRegistryVersionError,
    InvalidRegistryCursorError,
    RegistryAccessDeniedError,
    RegistryCategoryNotFoundError,
    RegistryOwnershipClaimConflictError,
    RegistryOwnershipClaimError,
    RegistryServerNotFoundError,
    RegistryVersionNotFoundError,
)
from app.modules.registry.schemas import (
    RegistryCategoryCreate,
    RegistryCategoryListResponse,
    RegistryCategoryRead,
    RegistryCategoryUpdate,
    RegistryOwnershipClaimResponse,
    RegistryPublishedServerListResponse,
    RegistryQualityScoreUpdate,
    RegistryServerDetailResponse,
    RegistryServerListResponse,
    RegistryServerOverviewTabResponse,
    RegistryServerSchemaTabResponse,
    RegistryServerScoreTabResponse,
    RegistryServerSummaryResponse,
    RegistryServerVersionCreate,
    RegistryServerVersionDetailResponse,
    RegistryServerVersionListResponse,
    RegistryServerVersionUpdate,
)
from app.modules.registry.service import (
    claim_server_ownership,
    create_category,
    create_server_version,
    delete_category,
    delete_server,
    delete_server_version,
    get_server_detail,
    get_server_overview_tab,
    get_server_schema_tab,
    get_server_score_tab,
    get_server_summary,
    get_version_detail,
    list_categories,
    list_published_servers,
    list_servers,
    list_versions,
    project_list_response_fields,
    set_latest_version,
    update_category,
    update_server_version,
    update_version_quality_score,
)
from app.modules.users.dependencies import (
    get_request_api_token,
    require_api_token_scopes,
    require_superuser_scopes,
)
from app.modules.users.models import User

catalog_router = APIRouter(prefix="/mcp/catalog", tags=["mcp"])
badges_router = APIRouter(prefix="/mcp/badges", tags=["mcp"])
public_router = APIRouter(prefix="/mcp/servers", tags=["mcp"])
categories_router = APIRouter(prefix="/mcp/categories", tags=["mcp-categories"])
admin_router = APIRouter(prefix="/admin/mcp/servers", tags=["admin-mcp"])


def score_badge_color(score: int | None) -> str:
    if score is None:
        return "#939393"
    if score >= 85:
        return "#4b0"
    if score >= 70:
        return "#67ac09"
    if score >= 50:
        return "#d8b800"
    return "#dd4343"


def quality_score_badge_value_metrics(value: str) -> tuple[int, int]:
    if value == "pending":
        return 55, 450
    if value == "100/100":
        return 57, 470
    if len(value) == len("0/100"):
        return 43, 330
    return 49, 390


def quality_score_badge_svg(score: int | None) -> str:
    label = "Wardn Score"
    value = f"{score}/100" if score is not None else "pending"
    label_width = 81
    label_text_length = 710
    label_text_x = 415
    value_width, value_text_length = quality_score_badge_value_metrics(value)
    value_text_x = int((label_width + (value_width / 2)) * 10 - 10)
    width = label_width + value_width
    color = score_badge_color(score)
    escaped_label = escape(label)
    escaped_value = escape(value)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" '
        f'role="img" aria-label="{escaped_label}: {escaped_value}">'
        f"<title>{escaped_label}: {escaped_value}</title>"
        '<filter id="blur"><feGaussianBlur stdDeviation="16"/></filter>'
        '<linearGradient id="s" x2="0" y2="100%">'
        '<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        '<stop offset="1" stop-opacity=".1"/>'
        "</linearGradient>"
        f'<clipPath id="r"><rect width="{width}" height="20" rx="3"/></clipPath>'
        '<g clip-path="url(#r)">'
        f'<rect width="{label_width}" height="20" fill="#555"/>'
        f'<rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>'
        f'<rect width="{width}" height="20" fill="url(#s)"/>'
        "</g>"
        '<g fill="#fff" text-anchor="middle" '
        'font-family="Verdana,Geneva,DejaVu Sans,sans-serif" '
        'text-rendering="geometricPrecision" font-size="110">'
        '<g transform="scale(.1)">'
        '<g aria-hidden="true" fill="#010101">'
        f'<text x="{label_text_x}" y="150" fill-opacity=".8" filter="url(#blur)" '
        f'textLength="{label_text_length}">{escaped_label}</text>'
        f'<text x="{label_text_x}" y="150" fill-opacity=".3" '
        f'textLength="{label_text_length}">{escaped_label}</text>'
        "</g>"
        f'<text x="{label_text_x}" y="140" textLength="{label_text_length}">{escaped_label}</text>'
        "</g>"
        '<g transform="scale(.1)">'
        '<g aria-hidden="true" fill="#010101">'
        f'<text x="{value_text_x}" y="150" fill-opacity=".8" filter="url(#blur)" '
        f'textLength="{value_text_length}">{escaped_value}</text>'
        f'<text x="{value_text_x}" y="150" fill-opacity=".3" '
        f'textLength="{value_text_length}">{escaped_value}</text>'
        "</g>"
        f'<text x="{value_text_x}" y="140" textLength="{value_text_length}">{escaped_value}</text>'
        "</g>"
        "</g>"
        "</svg>"
    )


@categories_router.get(
    "",
    response_model=RegistryCategoryListResponse,
    operation_id="mcp_categories_list",
)
async def list_mcp_categories(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RegistryCategoryListResponse:
    return await list_categories(session)


@categories_router.post(
    "",
    response_model=RegistryCategoryRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="mcp_categories_create",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def create_mcp_category(
    payload: RegistryCategoryCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _current_user: Annotated[User, Depends(require_superuser_scopes("registry:write"))],
) -> RegistryCategoryRead:
    try:
        response = await create_category(session, payload)
    except DuplicateRegistryCategoryError as exc:
        raise conflict(exc, detail="category slug already exists") from exc
    return await commit_response(session, response)


@categories_router.patch(
    "/{category_slug}",
    response_model=RegistryCategoryRead,
    operation_id="mcp_categories_update",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def update_mcp_category(
    category_slug: str,
    payload: RegistryCategoryUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _current_user: Annotated[User, Depends(require_superuser_scopes("registry:write"))],
) -> RegistryCategoryRead:
    try:
        response = await update_category(session, category_slug, payload)
    except RegistryCategoryNotFoundError as exc:
        raise not_found(exc) from exc
    except DuplicateRegistryCategoryError as exc:
        raise conflict(exc, detail="category slug already exists") from exc
    return await commit_response(session, response)


@categories_router.delete(
    "/{category_slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="mcp_categories_delete",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def delete_mcp_category(
    category_slug: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _current_user: Annotated[User, Depends(require_superuser_scopes("registry:write"))],
) -> None:
    try:
        await delete_category(session, category_slug)
    except RegistryCategoryNotFoundError as exc:
        raise not_found(exc) from exc
    await commit_session(session)


@public_router.get(
    "",
    response_model=RegistryServerListResponse,
    operation_id="mcp_servers_list",
)
async def list_mcp_servers(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    fields: str | None = None,
    search: str | None = None,
    updated_since: datetime | None = None,
    version: str | None = "latest",
    support_level: str | None = None,
    partner: bool | None = None,
    registry_type: str | None = None,
    transport_type: str | None = None,
    category: str | None = None,
) -> RegistryServerListResponse | JSONResponse:
    try:
        response = await list_servers(
            session,
            cursor=cursor,
            limit=limit,
            search=search,
            updated_since=updated_since,
            version=version,
            support_level=support_level,
            partner=partner,
            registry_type=registry_type,
            transport_type=transport_type,
            category=category,
        )
        projected = project_list_response_fields(response, fields=fields)
        if projected is not None:
            return JSONResponse(content=jsonable_encoder(projected))
        return response
    except InvalidRegistryCursorError as exc:
        raise bad_request(exc, detail="invalid cursor") from exc
    except ValueError as exc:
        raise bad_request(exc, detail="invalid fields") from exc


@catalog_router.get(
    "",
    response_model=RegistryPublishedServerListResponse,
    operation_id="mcp_catalog_list",
)
async def list_mcp_catalog(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    fields: str | None = None,
) -> RegistryPublishedServerListResponse | JSONResponse:
    try:
        response = await list_published_servers(session, page=page, per_page=20)
        projected = project_list_response_fields(response, fields=fields)
        if projected is not None:
            return JSONResponse(content=jsonable_encoder(projected))
        return response
    except ValueError as exc:
        raise bad_request(exc, detail="invalid fields") from exc


@badges_router.get(
    "/quality/{server_name:path}",
    operation_id="mcp_quality_score_badge",
    responses={
        status.HTTP_200_OK: {
            "content": {"image/svg+xml": {}},
            "description": "Quality score badge SVG.",
        },
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_mcp_quality_score_badge(
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    version: str | None = None,
) -> Response:
    try:
        if version:
            detail = await get_version_detail(session, server_name, version)
            score = detail.version.quality_score
        else:
            detail = await get_server_detail(session, server_name)
            score = detail.server.quality_score
    except (RegistryServerNotFoundError, RegistryVersionNotFoundError) as exc:
        detail = "server version not found" if version else "server not found"
        raise not_found(exc, detail=detail) from exc
    return Response(
        content=quality_score_badge_svg(score),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


@public_router.get(
    "/{server_name:path}/versions",
    response_model=RegistryServerVersionListResponse,
    operation_id="mcp_servers_list_versions",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def list_mcp_server_versions(
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RegistryServerVersionListResponse:
    try:
        return await list_versions(session, server_name)
    except RegistryServerNotFoundError as exc:
        raise not_found(exc, detail="server not found") from exc


@public_router.get(
    "/{server_name:path}/versions/{version}",
    response_model=RegistryServerVersionDetailResponse,
    operation_id="mcp_servers_get_version",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_mcp_server_version(
    server_name: str,
    version: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RegistryServerVersionDetailResponse:
    try:
        return await get_version_detail(session, server_name, version)
    except (RegistryServerNotFoundError, RegistryVersionNotFoundError) as exc:
        raise not_found(exc, detail="server version not found") from exc


@public_router.post(
    "/{server_name:path}/claim",
    response_model=RegistryOwnershipClaimResponse,
    operation_id="mcp_servers_claim_ownership",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def claim_mcp_server_ownership(
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("registry:write"))],
) -> RegistryOwnershipClaimResponse:
    try:
        response = await claim_server_ownership(session, server_name, current_user)
    except RegistryServerNotFoundError as exc:
        raise not_found(exc, detail="server not found") from exc
    except RegistryOwnershipClaimConflictError as exc:
        raise conflict(exc, detail=str(exc)) from exc
    except RegistryOwnershipClaimError as exc:
        raise bad_request(exc, detail=str(exc)) from exc
    return await commit_response(session, response)


@public_router.get(
    "/{server_name:path}/summary",
    response_model=RegistryServerSummaryResponse,
    operation_id="mcp_servers_get_summary",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_mcp_server_summary(
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RegistryServerSummaryResponse:
    try:
        return await get_server_summary(session, server_name)
    except RegistryServerNotFoundError as exc:
        raise not_found(exc, detail="server not found") from exc


@public_router.get(
    "/{server_name:path}/tabs/overview",
    response_model=RegistryServerOverviewTabResponse,
    operation_id="mcp_servers_get_overview_tab",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_mcp_server_overview_tab(
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RegistryServerOverviewTabResponse:
    try:
        return await get_server_overview_tab(session, server_name)
    except RegistryServerNotFoundError as exc:
        raise not_found(exc, detail="server not found") from exc


@public_router.get(
    "/{server_name:path}/tabs/schema",
    response_model=RegistryServerSchemaTabResponse,
    operation_id="mcp_servers_get_schema_tab",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_mcp_server_schema_tab(
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RegistryServerSchemaTabResponse:
    try:
        return await get_server_schema_tab(session, server_name)
    except RegistryServerNotFoundError as exc:
        raise not_found(exc, detail="server not found") from exc


@public_router.get(
    "/{server_name:path}/tabs/score",
    response_model=RegistryServerScoreTabResponse,
    operation_id="mcp_servers_get_score_tab",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_mcp_server_score_tab(
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RegistryServerScoreTabResponse:
    try:
        return await get_server_score_tab(session, server_name)
    except RegistryServerNotFoundError as exc:
        raise not_found(exc, detail="server not found") from exc


@public_router.get(
    "/{server_name:path}",
    response_model=RegistryServerDetailResponse,
    operation_id="mcp_servers_get",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_mcp_server(
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RegistryServerDetailResponse:
    try:
        return await get_server_detail(session, server_name)
    except RegistryServerNotFoundError as exc:
        raise not_found(exc, detail="server not found") from exc


@public_router.delete(
    "/{server_name:path}/versions/{version}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="mcp_servers_delete_version",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def delete_mcp_server_version(
    request: Request,
    server_name: str,
    version: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("registry:write"))],
) -> None:
    try:
        await delete_server_version(
            session,
            server_name,
            version,
            current_user=current_user,
            api_token=get_request_api_token(request),
            actor_user_id=current_user.id,
        )
    except RegistryAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except (RegistryServerNotFoundError, RegistryVersionNotFoundError) as exc:
        raise not_found(exc) from exc
    await commit_session(session)


@public_router.delete(
    "/{server_name:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="mcp_servers_delete",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def delete_mcp_server(
    request: Request,
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("registry:write"))],
) -> None:
    try:
        await delete_server(
            session,
            server_name,
            current_user=current_user,
            api_token=get_request_api_token(request),
            actor_user_id=current_user.id,
        )
    except RegistryAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except RegistryServerNotFoundError as exc:
        raise not_found(exc) from exc
    await commit_session(session)


@admin_router.post(
    "",
    response_model=RegistryServerVersionDetailResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="admin_mcp_servers_create_version",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def admin_create_mcp_server_version(
    payload: RegistryServerVersionCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_superuser_scopes("registry:write"))],
) -> RegistryServerVersionDetailResponse:
    try:
        response = await create_server_version(
            session,
            payload,
            owner_user_id=current_user.id,
            created_by_user_id=current_user.id,
            updated_by_user_id=current_user.id,
            publisher_user_id=current_user.id,
        )
    except DuplicateRegistryVersionError as exc:
        raise conflict(exc, detail="server version already exists") from exc
    return await commit_response(session, response)


@admin_router.put(
    "/{server_name:path}/versions/{version}",
    response_model=RegistryServerVersionDetailResponse,
    operation_id="admin_mcp_servers_update_version",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def admin_update_mcp_server_version(
    server_name: str,
    version: str,
    payload: RegistryServerVersionUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_superuser_scopes("registry:write"))],
) -> RegistryServerVersionDetailResponse:
    try:
        response = await update_server_version(
            session,
            server_name,
            version,
            payload,
            updated_by_user_id=current_user.id,
    )
    except (RegistryServerNotFoundError, RegistryVersionNotFoundError) as exc:
        raise not_found(exc) from exc
    return await commit_response(session, response)


@admin_router.post(
    "/{server_name:path}/versions/{version}/latest",
    response_model=RegistryServerVersionDetailResponse,
    operation_id="admin_mcp_servers_set_latest_version",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def admin_set_latest_mcp_server_version(
    server_name: str,
    version: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _current_user: Annotated[User, Depends(require_superuser_scopes("registry:write"))],
) -> RegistryServerVersionDetailResponse:
    try:
        response = await set_latest_version(session, server_name, version)
    except (RegistryServerNotFoundError, RegistryVersionNotFoundError) as exc:
        raise not_found(exc) from exc
    return await commit_response(session, response)


@admin_router.patch(
    "/{server_name:path}/versions/{version}/quality-score",
    response_model=RegistryServerVersionDetailResponse,
    operation_id="admin_mcp_servers_update_version_quality_score",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def admin_update_mcp_server_version_quality_score(
    server_name: str,
    version: str,
    payload: RegistryQualityScoreUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _current_user: Annotated[User, Depends(require_superuser_scopes("registry:score"))],
) -> RegistryServerVersionDetailResponse:
    try:
        response = await update_version_quality_score(
            session,
            server_name,
            version,
            payload.quality_score,
            trust_report=payload.trust_report,
        )
    except (RegistryServerNotFoundError, RegistryVersionNotFoundError) as exc:
        raise not_found(exc) from exc
    return await commit_response(session, response)


@admin_router.delete(
    "/{server_name:path}/versions/{version}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="admin_mcp_servers_delete_version",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def admin_delete_mcp_server_version(
    server_name: str,
    version: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_superuser_scopes("registry:write"))],
) -> None:
    try:
        await delete_server_version(
            session,
            server_name,
            version,
            current_user=current_user,
            actor_user_id=current_user.id,
        )
    except (RegistryServerNotFoundError, RegistryVersionNotFoundError) as exc:
        raise not_found(exc) from exc
    await commit_session(session)


@admin_router.delete(
    "/{server_name:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="admin_mcp_servers_delete",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def admin_delete_mcp_server(
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_superuser_scopes("registry:write"))],
) -> None:
    try:
        await delete_server(
            session,
            server_name,
            current_user=current_user,
            actor_user_id=current_user.id,
        )
    except RegistryServerNotFoundError as exc:
        raise not_found(exc) from exc
    await commit_session(session)
