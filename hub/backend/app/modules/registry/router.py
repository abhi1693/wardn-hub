from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.registry.exceptions import (
    DuplicateRegistryCategoryError,
    DuplicateRegistryVersionError,
    InvalidRegistryCursorError,
    RegistryCategoryNotFoundError,
    RegistryServerNotFoundError,
    RegistryVersionNotFoundError,
)
from app.modules.registry.schemas import (
    RegistryCategoryCreate,
    RegistryCategoryListResponse,
    RegistryCategoryRead,
    RegistryCategoryUpdate,
    RegistryPublishedServerListResponse,
    RegistryServerDetailResponse,
    RegistryServerListResponse,
    RegistryServerVersionCreate,
    RegistryServerVersionDetailResponse,
    RegistryServerVersionListResponse,
    RegistryServerVersionUpdate,
)
from app.modules.registry.service import (
    create_category,
    create_server_version,
    delete_category,
    delete_server,
    delete_server_version,
    get_server_detail,
    get_version_detail,
    list_categories,
    list_published_servers,
    list_servers,
    list_versions,
    set_latest_version,
    update_category,
    update_server_version,
)
from app.modules.users.dependencies import require_superuser
from app.modules.users.models import User

catalog_router = APIRouter(prefix="/mcp/catalog", tags=["mcp"])
public_router = APIRouter(prefix="/mcp/servers", tags=["mcp"])
categories_router = APIRouter(prefix="/mcp/categories", tags=["mcp-categories"])
admin_router = APIRouter(prefix="/admin/mcp/servers", tags=["admin-mcp"])


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
    _current_user: Annotated[User, Depends(require_superuser)],
) -> RegistryCategoryRead:
    try:
        response = await create_category(session, payload)
    except DuplicateRegistryCategoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="category slug already exists",
        ) from exc
    await session.commit()
    return response


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
    _current_user: Annotated[User, Depends(require_superuser)],
) -> RegistryCategoryRead:
    try:
        response = await update_category(session, category_slug, payload)
    except RegistryCategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateRegistryCategoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="category slug already exists",
        ) from exc
    await session.commit()
    return response


@categories_router.delete(
    "/{category_slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="mcp_categories_delete",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def delete_mcp_category(
    category_slug: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _current_user: Annotated[User, Depends(require_superuser)],
) -> None:
    try:
        await delete_category(session, category_slug)
    except RegistryCategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()


@public_router.get(
    "",
    response_model=RegistryServerListResponse,
    operation_id="mcp_servers_list",
)
async def list_mcp_servers(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    search: str | None = None,
    updated_since: datetime | None = None,
    version: str | None = "latest",
    include_deleted: bool = False,
    support_level: str | None = None,
    partner: bool | None = None,
    registry_type: str | None = None,
    transport_type: str | None = None,
    category: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
) -> RegistryServerListResponse:
    try:
        return await list_servers(
            session,
            cursor=cursor,
            limit=limit,
            include_deleted=include_deleted,
            search=search,
            updated_since=updated_since,
            version=version,
            support_level=support_level,
            partner=partner,
            registry_type=registry_type,
            transport_type=transport_type,
            category=category,
            status=status_filter,
        )
    except InvalidRegistryCursorError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid cursor",
        ) from exc


@catalog_router.get(
    "",
    response_model=RegistryPublishedServerListResponse,
    operation_id="mcp_catalog_list",
)
async def list_mcp_catalog(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
) -> RegistryPublishedServerListResponse:
    return await list_published_servers(session, page=page, per_page=20)


@public_router.get(
    "/{server_name:path}/versions",
    response_model=RegistryServerVersionListResponse,
    operation_id="mcp_servers_list_versions",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def list_mcp_server_versions(
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    include_deleted: bool = False,
) -> RegistryServerVersionListResponse:
    try:
        return await list_versions(session, server_name, include_deleted=include_deleted)
    except RegistryServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="server not found",
        ) from exc


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
    include_deleted: bool = False,
) -> RegistryServerVersionDetailResponse:
    try:
        return await get_version_detail(
            session,
            server_name,
            version,
            include_deleted=include_deleted,
        )
    except (RegistryServerNotFoundError, RegistryVersionNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="server version not found",
        ) from exc


@public_router.get(
    "/{server_name:path}",
    response_model=RegistryServerDetailResponse,
    operation_id="mcp_servers_get",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_mcp_server(
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    include_deleted: bool = False,
) -> RegistryServerDetailResponse:
    try:
        return await get_server_detail(session, server_name, include_deleted=include_deleted)
    except RegistryServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="server not found",
        ) from exc


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
    current_user: Annotated[User, Depends(require_superuser)],
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="server version already exists",
        ) from exc
    await session.commit()
    return response


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
    current_user: Annotated[User, Depends(require_superuser)],
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
    return response


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
    _current_user: Annotated[User, Depends(require_superuser)],
) -> RegistryServerVersionDetailResponse:
    try:
        response = await set_latest_version(session, server_name, version)
    except (RegistryServerNotFoundError, RegistryVersionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
    return response


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
    _current_user: Annotated[User, Depends(require_superuser)],
) -> None:
    try:
        await delete_server_version(session, server_name, version)
    except (RegistryServerNotFoundError, RegistryVersionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()


@admin_router.delete(
    "/{server_name:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="admin_mcp_servers_delete",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def admin_delete_mcp_server(
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _current_user: Annotated[User, Depends(require_superuser)],
) -> None:
    try:
        await delete_server(session, server_name)
    except RegistryServerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
