import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.router import (
    commit_and_refresh,
    commit_session,
    conflict,
    forbidden,
    not_found,
    unauthorized,
)
from app.core.schemas import ErrorResponse
from app.core.security import create_session_token
from app.db.session import get_db_session
from app.modules.users.dependencies import (
    get_current_user,
    require_api_token_scopes,
)
from app.modules.users.exceptions import (
    DuplicateUserError,
    InvalidAPITokenScopeError,
    InvalidLoginError,
    OIDCAuthenticationError,
    OIDCConfigurationError,
    UserAPITokenNotFoundError,
)
from app.modules.users.models import User
from app.modules.users.oidc import (
    OIDC_STATE_TTL_SECONDS,
    authorization_url,
    create_oidc_state,
    exchange_oidc_code,
    fetch_oidc_metadata,
    frontend_redirect_url,
    oidc_enabled,
    oidc_state_cookie_name,
    verify_oidc_identity,
    verify_oidc_state,
)
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
    authenticate_oidc_identity,
    create_user,
    create_user_api_token,
    delete_user_api_token,
    is_auth_provider_enabled,
    list_auth_providers,
    list_user_api_tokens,
    rotate_user_api_token,
    update_user_api_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


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


def clear_oidc_state_cookie(response: Response, state: str | None = None) -> None:
    settings = get_settings()
    cookie_names = [settings.oidc_state_cookie_name]
    keyed_name = oidc_state_cookie_name(settings, state)
    if keyed_name not in cookie_names:
        cookie_names.append(keyed_name)

    for cookie_name in cookie_names:
        response.delete_cookie(
            key=cookie_name,
            httponly=True,
            secure=settings.environment != "local",
            samesite="lax",
            path="/",
        )


def get_oidc_state_cookie(request: Request, state: str) -> str | None:
    settings = get_settings()
    keyed_cookie = request.cookies.get(oidc_state_cookie_name(settings, state))
    if keyed_cookie:
        return keyed_cookie
    return request.cookies.get(settings.oidc_state_cookie_name)


def set_oidc_state_cookie(response: Response, state: str, state_cookie: str) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.oidc_state_cookie_name,
        httponly=True,
        secure=settings.environment != "local",
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key=oidc_state_cookie_name(settings, state),
        value=state_cookie,
        httponly=True,
        secure=settings.environment != "local",
        samesite="lax",
        max_age=OIDC_STATE_TTL_SECONDS,
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
        raise forbidden(detail="local authentication is disabled")
    try:
        user = await authenticate_local_user(session, payload)
    except InvalidLoginError as exc:
        raise unauthorized(exc, detail="invalid email or password") from exc

    set_session_cookie(response, user.id)
    return UserRead.model_validate(await commit_and_refresh(session, user))


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
        raise forbidden(detail="local registration is disabled")
    try:
        user = await create_user(session, payload, is_superuser=False)
    except DuplicateUserError as exc:
        raise conflict(exc, detail="email already exists") from exc

    set_session_cookie(response, user.id)
    return UserRead.model_validate(await commit_and_refresh(session, user))


@router.get(
    "/oidc/login",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    operation_id="auth_oidc_login",
    responses={
        status.HTTP_302_FOUND: {"description": "Redirect to the configured OIDC provider."},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": "OIDC authentication is not configured.",
        },
    },
)
async def oidc_login(
    redirect_to: Annotated[str | None, Query(alias="redirectTo")] = None,
) -> RedirectResponse:
    settings = get_settings()
    if not oidc_enabled(settings):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OIDC auth is not enabled",
        )
    try:
        oidc_state, state_cookie = create_oidc_state(settings, redirect_to=redirect_to)
        metadata = await fetch_oidc_metadata(settings)
        location = authorization_url(settings, metadata, oidc_state)
    except OIDCConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    response = RedirectResponse(location, status_code=status.HTTP_302_FOUND)
    set_oidc_state_cookie(response, oidc_state.state, state_cookie)
    return response


@router.get(
    "/oidc/callback",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    operation_id="auth_oidc_callback",
    responses={
        status.HTTP_302_FOUND: {"description": "Redirect to the Wardn Hub frontend."},
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "OIDC authentication failed.",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": "OIDC authentication is not configured.",
        },
    },
)
async def oidc_callback(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    settings = get_settings()
    if not oidc_enabled(settings):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OIDC auth is not enabled",
        )
    if error:
        response = RedirectResponse(
            frontend_redirect_url(settings, "/login?error=oidc"),
            status_code=status.HTTP_302_FOUND,
        )
        logger.warning("OIDC callback returned provider error")
        clear_oidc_state_cookie(response, state)
        return response
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing OIDC callback code or state",
        )

    state_cookie = get_oidc_state_cookie(request, state)
    if not state_cookie:
        logger.warning("OIDC callback failed: missing state cookie")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing OIDC state",
        )

    try:
        verified_state = verify_oidc_state(settings, state_cookie, state)
        metadata = await fetch_oidc_metadata(settings)
        token_response = await exchange_oidc_code(settings, metadata, code=code)
        oidc_identity = await verify_oidc_identity(
            settings,
            metadata,
            token_response,
            nonce=verified_state.nonce,
        )
        user = await authenticate_oidc_identity(
            session,
            oidc_identity,
            auto_create_users=settings.oidc_auto_create_users,
            superuser_emails=settings.oidc_superuser_emails,
        )
    except OIDCConfigurationError as exc:
        logger.warning("OIDC callback failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except OIDCAuthenticationError as exc:
        logger.warning("OIDC callback failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    response = RedirectResponse(
        frontend_redirect_url(settings, verified_state.redirect_to),
        status_code=status.HTTP_302_FOUND,
    )
    set_session_cookie(response, user.id)
    clear_oidc_state_cookie(response, verified_state.state)
    await commit_session(session)
    return response


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
    try:
        record, token = await create_user_api_token(session, current_user.id, payload)
    except InvalidAPITokenScopeError as exc:
        raise forbidden(exc, detail=str(exc)) from exc
    record = await commit_and_refresh(session, record)
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
    except InvalidAPITokenScopeError as exc:
        raise forbidden(exc, detail=str(exc)) from exc
    except UserAPITokenNotFoundError as exc:
        raise not_found(exc) from exc
    return UserAPITokenRead.model_validate(await commit_and_refresh(session, record))


@router.post(
    "/api-tokens/{token_id}/rotate",
    response_model=UserAPITokenCreated,
    operation_id="auth_rotate_api_token",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def rotate_api_token(
    token_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("tokens:write"))],
) -> UserAPITokenCreated:
    try:
        record, token = await rotate_user_api_token(session, current_user.id, token_id)
    except UserAPITokenNotFoundError as exc:
        raise not_found(exc) from exc
    record = await commit_and_refresh(session, record)
    return UserAPITokenCreated(
        token=token,
        record=UserAPITokenRead.model_validate(record),
    )


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
        raise not_found(exc) from exc
    await commit_session(session)
