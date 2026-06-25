from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import verify_session_token
from app.db.session import get_db_session
from app.modules.users import repository
from app.modules.users.auth_providers import verify_external_bearer_token
from app.modules.users.exceptions import InvalidLoginError
from app.modules.users.models import User, UserAPIToken
from app.modules.users.schemas import APITokenScope
from app.modules.users.service import authenticate_api_token, get_or_create_external_user

API_TOKEN_STATE_KEY = "wardn_hub_api_token"
CLERK_SESSION_COOKIE_NAME = "__session"


def get_request_api_token(request: Request) -> UserAPIToken | None:
    return getattr(request.state, API_TOKEN_STATE_KEY, None)


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    user_id = None
    settings = get_settings()
    setattr(request.state, API_TOKEN_STATE_KEY, None)
    session_token = request.cookies.get(settings.session_cookie_name)

    if session_token:
        user_id = verify_session_token(session_token)

    plaintext_token = ""
    if user_id is None and authorization and authorization.lower().startswith("bearer "):
        plaintext_token = authorization.removeprefix("Bearer ").removeprefix("bearer ").strip()
    if user_id is None and not plaintext_token:
        plaintext_token = request.cookies.get(CLERK_SESSION_COOKIE_NAME, "").strip()

    if user_id is None and plaintext_token:
        authenticated = await authenticate_api_token(session, plaintext_token)
        if authenticated:
            user, _api_token = authenticated
            setattr(request.state, API_TOKEN_STATE_KEY, _api_token)
            return user
        external_claims = await verify_external_bearer_token(plaintext_token)
        if external_claims is not None:
            try:
                user = await get_or_create_external_user(session, external_claims)
            except InvalidLoginError:
                user = None
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="authentication required",
                )
            await session.commit()
            await session.refresh(user)
            return user

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )

    user = await repository.get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    return user


async def get_optional_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    try:
        return await get_current_user(request, session, authorization)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            return None
        raise


def require_api_token_scopes(
    *required_scopes: APITokenScope,
):
    async def dependency(
        request: Request,
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        api_token = get_request_api_token(request)
        if api_token is None:
            return current_user

        token_scopes = set(api_token.scopes)
        missing_scopes = [scope for scope in required_scopes if scope not in token_scopes]
        if missing_scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API token missing required scope: {', '.join(missing_scopes)}",
            )
        return current_user

    return dependency


async def require_superuser(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="superuser access required",
        )
    return current_user


async def require_global_moderator(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_superuser and not current_user.is_global_moderator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="moderator access required",
        )
    return current_user


async def require_global_partner_manager(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_superuser and not current_user.is_global_partner_manager:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="partner manager access required",
        )
    return current_user
