from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.router import bad_request, commit_response, conflict, not_found
from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.registry.schemas import RegistryUserDetailResponse
from app.modules.registry.service import (
    get_registry_user_detail,
    list_registry_users,
    public_user_login,
    public_user_name,
)
from app.modules.users.dependencies import (
    get_optional_current_user,
    require_request_api_token_scopes,
    require_superuser_scopes,
)
from app.modules.users.exceptions import (
    BootstrapUserExistsError,
    InvalidUserRoleUpdateError,
    UserNotFoundError,
)
from app.modules.users.models import User
from app.modules.users.schemas import (
    BootstrapUserCreate,
    UserAdminUpdate,
    UserDirectoryListResponse,
    UserDirectoryRead,
    UserRead,
)
from app.modules.users.service import bootstrap_superuser, list_users, update_user_admin_flags

router = APIRouter(prefix="/users", tags=["users"])


def user_directory_record(user: User, *, include_admin: bool = False) -> UserDirectoryRead:
    admin_fields = (
        {
            "email": user.email,
            "firstName": user.first_name,
            "lastName": user.last_name,
            "displayName": user.display_name,
            "isActive": user.is_active,
            "isSuperuser": user.is_superuser,
            "isGlobalModerator": user.is_global_moderator,
            "isGlobalPartnerManager": user.is_global_partner_manager,
            "lastLoginAt": user.last_login_at,
            "createdAt": user.created_at,
            "updatedAt": user.updated_at,
        }
        if include_admin
        else {}
    )
    return UserDirectoryRead(
        id=user.id,
        login=public_user_login(user),
        name=public_user_name(user),
        htmlUrl=f"/users/{user.id}",
        **admin_fields,
    )


@router.post(
    "/bootstrap",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="users_bootstrap",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def bootstrap_user(
    payload: BootstrapUserCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRead:
    try:
        user = await bootstrap_superuser(session, payload)
    except BootstrapUserExistsError as exc:
        raise conflict(exc, detail="bootstrap user already exists") from exc
    return UserRead.model_validate(user)


@router.get(
    "",
    response_model=UserDirectoryListResponse,
    operation_id="users_list",
)
async def list_user_records(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
) -> UserDirectoryListResponse:
    if current_user is not None and current_user.is_superuser:
        require_request_api_token_scopes(request, "users:read")
        users = await list_users(session)
        return UserDirectoryListResponse(
            users=[user_directory_record(user, include_admin=True) for user in users]
        )

    response = await list_registry_users(session)
    return UserDirectoryListResponse(
        users=[
            UserDirectoryRead(
                id=user.id,
                login=user.login,
                name=user.name,
                avatarUrl=user.avatar_url,
                htmlUrl=user.html_url,
            )
            for user in response.users
        ]
    )


@router.get(
    "/{user_id}",
    response_model=RegistryUserDetailResponse,
    operation_id="users_get",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_user_record(
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
        raise not_found(exc, detail="user not found") from exc


@router.patch(
    "/{user_id}",
    response_model=UserDirectoryRead,
    operation_id="users_update_admin_flags",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def update_user_record_admin_flags(
    user_id: UUID,
    payload: UserAdminUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_superuser_scopes("users:write"))],
) -> UserDirectoryRead:
    try:
        user = await update_user_admin_flags(session, current_user, user_id, payload)
    except UserNotFoundError as exc:
        raise not_found(exc) from exc
    except InvalidUserRoleUpdateError as exc:
        raise bad_request(exc) from exc
    return user_directory_record(
        await commit_response(session, user),
        include_admin=True,
    )
