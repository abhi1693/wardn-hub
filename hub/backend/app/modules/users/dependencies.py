from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from opentelemetry import trace
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
tracer = trace.get_tracer(__name__)


def set_user_id_attribute(span: trace.Span, user: User) -> None:
    user_id = getattr(user, "id", None)
    if user_id is not None:
        span.set_attribute("auth.user_id", str(user_id))


def get_request_api_token(request: Request) -> UserAPIToken | None:
    return getattr(request.state, API_TOKEN_STATE_KEY, None)


def require_request_api_token_scopes(
    request: Request,
    *required_scopes: APITokenScope,
) -> None:
    api_token = get_request_api_token(request)
    if api_token is None:
        return

    token_scopes = set(api_token.scopes)
    missing_scopes = [scope for scope in required_scopes if scope not in token_scopes]
    if missing_scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API token missing required scope: {', '.join(missing_scopes)}",
        )


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    with tracer.start_as_current_span("auth.current_user") as span:
        user_id = None
        settings = get_settings()
        setattr(request.state, API_TOKEN_STATE_KEY, None)
        session_token = request.cookies.get(settings.session_cookie_name)
        span.set_attribute("auth.has_session_cookie", bool(session_token))
        span.set_attribute(
            "auth.has_authorization_bearer",
            bool(authorization and authorization.lower().startswith("bearer ")),
        )

        if session_token:
            with tracer.start_as_current_span("auth.verify_session_token") as verify_span:
                user_id = verify_session_token(session_token)
                verify_span.set_attribute("auth.session.valid", user_id is not None)

        plaintext_token = ""
        if user_id is None and authorization and authorization.lower().startswith("bearer "):
            plaintext_token = authorization.removeprefix("Bearer ").removeprefix("bearer ").strip()
        if user_id is None and not plaintext_token:
            plaintext_token = request.cookies.get(CLERK_SESSION_COOKIE_NAME, "").strip()
            span.set_attribute("auth.has_clerk_cookie", bool(plaintext_token))

        if user_id is None and plaintext_token:
            span.set_attribute("auth.path", "bearer")
            with tracer.start_as_current_span("auth.api_token_lookup") as token_span:
                authenticated = await authenticate_api_token(session, plaintext_token)
                token_span.set_attribute("auth.api_token.matched", authenticated is not None)
            if authenticated:
                user, _api_token = authenticated
                setattr(request.state, API_TOKEN_STATE_KEY, _api_token)
                span.set_attribute("auth.result", "api_token")
                set_user_id_attribute(span, user)
                return user

            with tracer.start_as_current_span("auth.external_token_lookup") as external_span:
                external_claims = await verify_external_bearer_token(plaintext_token)
                external_span.set_attribute(
                    "auth.external.matched",
                    external_claims is not None,
                )
                if external_claims is not None:
                    external_span.set_attribute("auth.external.provider", external_claims.provider)
            if external_claims is not None:
                with tracer.start_as_current_span("auth.external_user_lookup") as user_span:
                    user_span.set_attribute("auth.external.provider", external_claims.provider)
                    try:
                        user = await get_or_create_external_user(session, external_claims)
                    except InvalidLoginError:
                        user = None
                    user_span.set_attribute("auth.user.found", user is not None)
                if user is None:
                    span.set_attribute("auth.result", "unauthorized")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="authentication required",
                    )
                await session.commit()
                await session.refresh(user)
                span.set_attribute("auth.result", "external")
                set_user_id_attribute(span, user)
                return user

        if user_id is None:
            span.set_attribute("auth.result", "unauthorized")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication required",
            )

        span.set_attribute("auth.path", "session")
        with tracer.start_as_current_span("auth.session_user_lookup") as lookup_span:
            lookup_span.set_attribute("auth.user_id", str(user_id))
            user = await repository.get_user_by_id(session, user_id)
            lookup_span.set_attribute("auth.user.found", user is not None)
            lookup_span.set_attribute("auth.user.active", bool(user and user.is_active))
        if user is None or not user.is_active:
            span.set_attribute("auth.result", "unauthorized")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication required",
            )
        span.set_attribute("auth.result", "session")
        set_user_id_attribute(span, user)
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
        require_request_api_token_scopes(request, *required_scopes)
        return current_user

    return dependency

def ensure_superuser(current_user: User) -> None:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="superuser access required",
        )


def ensure_global_moderator(current_user: User) -> None:
    if not current_user.is_superuser and not current_user.is_global_moderator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="moderator access required",
        )


def ensure_global_partner_manager(current_user: User) -> None:
    if not current_user.is_superuser and not current_user.is_global_partner_manager:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="partner manager access required",
        )


def require_superuser_scopes(
    *required_scopes: APITokenScope,
):
    async def dependency(
        request: Request,
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        ensure_superuser(current_user)
        require_request_api_token_scopes(request, *required_scopes)
        return current_user

    return dependency


def require_global_moderator_scopes(
    *required_scopes: APITokenScope,
):
    async def dependency(
        request: Request,
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        ensure_global_moderator(current_user)
        require_request_api_token_scopes(request, *required_scopes)
        return current_user

    return dependency


def require_global_partner_manager_scopes(
    *required_scopes: APITokenScope,
):
    async def dependency(
        request: Request,
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        ensure_global_partner_manager(current_user)
        require_request_api_token_scopes(request, *required_scopes)
        return current_user

    return dependency
