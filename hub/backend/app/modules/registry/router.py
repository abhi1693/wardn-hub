from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.registry.exceptions import (
    DuplicateRegistryVersionError,
    InvalidRegistryCursorError,
    RegistryServerNotFoundError,
    RegistryVersionNotFoundError,
)
from app.modules.registry.schemas import (
    RegistryCategoryListResponse,
    RegistryServerDetailResponse,
    RegistryServerListResponse,
    RegistryServerVersionCreate,
    RegistryServerVersionDetailResponse,
    RegistryServerVersionListResponse,
    RegistryServerVersionUpdate,
    RegistryUserDetailResponse,
    RegistryUserListResponse,
)
from app.modules.registry.service import (
    create_server_version,
    delete_server,
    delete_server_version,
    get_registry_user_detail,
    get_server_detail,
    get_version_detail,
    list_categories,
    list_registry_users,
    list_servers,
    list_versions,
    set_latest_version,
    update_server_version,
)
from app.modules.users.dependencies import require_superuser
from app.modules.users.exceptions import UserNotFoundError
from app.modules.users.models import User

public_router = APIRouter(prefix="/mcp/servers", tags=["mcp"])
categories_router = APIRouter(prefix="/mcp/categories", tags=["mcp-categories"])
users_router = APIRouter(prefix="/mcp/users", tags=["mcp-users"])
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


@users_router.get(
    "",
    response_model=RegistryUserListResponse,
    operation_id="mcp_users_list",
)
async def list_mcp_users(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RegistryUserListResponse:
    return await list_registry_users(session)


@users_router.get(
    "/{user_id}",
    response_model=RegistryUserDetailResponse,
    operation_id="mcp_users_get",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_mcp_user(
    user_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RegistryUserDetailResponse:
    try:
        return await get_registry_user_detail(
            session,
            user_id,
            cursor=cursor,
            limit=limit,
        )
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user not found",
        ) from exc


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
