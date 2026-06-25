from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.schemas import ErrorResponse
from app.core.security import create_session_token
from app.db.session import get_db_session
from app.modules.users.auth_providers import is_auth_provider_enabled
from app.modules.users.dependencies import (
    CLERK_SESSION_COOKIE_NAME,
    get_current_user,
    require_api_token_scopes,
)
from app.modules.users.exceptions import (
    DuplicateUserError,
    InvalidLoginError,
    UserAPITokenNotFoundError,
)
from app.modules.users.models import User
from app.modules.users.schemas import (
    AuthProviderListResponse,
    LoginRequest,
    UserAPITokenCreate,
    UserAPITokenCreated,
    UserAPITokenListResponse,
    UserAPITokenRead,
    UserAPITokenUpdate,
    UserCreate,
    UserRead,
)
from app.modules.users.service import (
    authenticate_local_user,
    create_user,
    create_user_api_token,
    delete_user_api_token,
    list_auth_providers,
    list_user_api_tokens,
    update_user_api_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def set_session_cookie(response: Response, user_id: UUID) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=create_session_token(user_id),
        httponly=True,
        secure=settings.environment != "local",
        samesite="lax",
        max_age=settings.session_ttl_seconds,
        path="/",
    )


@router.get(
    "/providers",
    response_model=AuthProviderListResponse,
    operation_id="auth_list_providers",
)
async def providers() -> AuthProviderListResponse:
    return list_auth_providers()


@router.post(
    "/login",
    response_model=UserRead,
    operation_id="auth_login",
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)
async def login(
    payload: LoginRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRead:
    if not is_auth_provider_enabled("local"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="local authentication is disabled",
        )
    try:
        user = await authenticate_local_user(session, payload)
    except InvalidLoginError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        ) from exc

    set_session_cookie(response, user.id)
    await session.commit()
    await session.refresh(user)
    return UserRead.model_validate(user)


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="auth_register",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def register(
    payload: UserCreate,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRead:
    if not is_auth_provider_enabled("local"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="local registration is disabled",
        )
    try:
        user = await create_user(session, payload, is_superuser=False)
    except DuplicateUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email already exists",
        ) from exc

    set_session_cookie(response, user.id)
    await session.commit()
    await session.refresh(user)
    return UserRead.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, operation_id="auth_logout")
async def logout(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.environment != "local",
        samesite="lax",
        path="/",
    )
    response.delete_cookie(
        key=CLERK_SESSION_COOKIE_NAME,
        secure=settings.environment != "local",
        samesite="lax",
        path="/",
    )


@router.get("/me", response_model=UserRead, operation_id="auth_me")
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> UserRead:
    return UserRead.model_validate(current_user)


@router.post(
    "/api-tokens",
    response_model=UserAPITokenCreated,
    status_code=status.HTTP_201_CREATED,
    operation_id="auth_create_api_token",
)
async def create_api_token(
    payload: UserAPITokenCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("tokens:write"))],
) -> UserAPITokenCreated:
    record, token = await create_user_api_token(session, current_user.id, payload)
    await session.commit()
    await session.refresh(record)
    return UserAPITokenCreated(
        token=token,
        record=UserAPITokenRead.model_validate(record),
    )


@router.get(
    "/api-tokens",
    response_model=UserAPITokenListResponse,
    operation_id="auth_list_api_tokens",
)
async def list_api_tokens(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("tokens:read"))],
) -> UserAPITokenListResponse:
    records = await list_user_api_tokens(session, current_user.id)
    return UserAPITokenListResponse(
        tokens=[UserAPITokenRead.model_validate(record) for record in records]
    )


@router.patch(
    "/api-tokens/{token_id}",
    response_model=UserAPITokenRead,
    operation_id="auth_update_api_token",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def update_api_token(
    token_id: UUID,
    payload: UserAPITokenUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("tokens:write"))],
) -> UserAPITokenRead:
    try:
        record = await update_user_api_token(session, current_user.id, token_id, payload)
    except UserAPITokenNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(record)
    return UserAPITokenRead.model_validate(record)


@router.delete(
    "/api-tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="auth_delete_api_token",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def delete_api_token(
    token_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("tokens:write"))],
) -> None:
    try:
        await delete_user_api_token(session, current_user.id, token_id)
    except UserAPITokenNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
