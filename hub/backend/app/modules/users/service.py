import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    extract_api_token_key,
    generate_api_token,
    hash_api_token,
    hash_password,
    verify_api_token,
    verify_password,
)
from app.modules.users import repository
from app.modules.users.exceptions import (
    BootstrapUserExistsError,
    DuplicateUserError,
    InvalidAPITokenScopeError,
    InvalidLoginError,
    InvalidUserRoleUpdateError,
    OIDCAuthenticationError,
    UserAPITokenNotFoundError,
    UserNotFoundError,
)
from app.modules.users.models import LocalAuthCredential, User, UserAPIToken, UserExternalIdentity
from app.modules.users.oidc import OIDCIdentity, oidc_configured, oidc_identity_provider_key
from app.modules.users.schemas import (
    ALL_API_TOKEN_SCOPES,
    APITokenScope,
    AuthProviderListResponse,
    AuthProviderRead,
    LoginRequest,
    UserAdminUpdate,
    UserAPITokenCreate,
    UserAPITokenUpdate,
    UserCreate,
)

BASE_API_TOKEN_SCOPES: set[APITokenScope] = {
    "catalog:read",
    "events:read",
    "events:write",
    "submissions:read",
    "submissions:write",
    "tokens:read",
    "tokens:write",
}
MODERATOR_API_TOKEN_SCOPES: set[APITokenScope] = {"submissions:moderate"}
PARTNER_MANAGER_API_TOKEN_SCOPES: set[APITokenScope] = {"partners:write"}
SUPERUSER_API_TOKEN_SCOPES: set[APITokenScope] = set(ALL_API_TOKEN_SCOPES)
OIDC_PUBLIC_PROVIDER_KEY = "oidc"


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def enabled_auth_providers() -> list[str]:
    return get_settings().auth_providers


def is_auth_provider_enabled(provider: str) -> bool:
    return provider in enabled_auth_providers()


def unique_uuid_strings(values: list[uuid.UUID]) -> list[str]:
    return sorted({str(value) for value in values})


def unique_scope_strings(values: list[APITokenScope]) -> list[str]:
    return sorted(set(values))


def allowed_api_token_scopes(user: User) -> set[APITokenScope]:
    if user.is_superuser:
        return SUPERUSER_API_TOKEN_SCOPES.copy()

    scopes = BASE_API_TOKEN_SCOPES.copy()
    if user.is_global_moderator:
        scopes.update(MODERATOR_API_TOKEN_SCOPES)
    if user.is_global_partner_manager:
        scopes.update(PARTNER_MANAGER_API_TOKEN_SCOPES)
    return scopes


def validate_api_token_scopes(user: User, scopes: list[APITokenScope]) -> None:
    denied = sorted(set(scopes) - allowed_api_token_scopes(user))
    if denied:
        raise InvalidAPITokenScopeError(
            f"API token scope not allowed for current user: {', '.join(denied)}"
        )


def auth_provider_label(provider: str) -> str:
    if provider == OIDC_PUBLIC_PROVIDER_KEY:
        return get_settings().oidc_provider_name.strip() or "OpenID Connect"
    return "Email and password"


def apply_oidc_profile(user: User, identity: OIDCIdentity) -> None:
    first_name = identity.first_name.strip()
    last_name = identity.last_name.strip()
    if first_name:
        user.first_name = first_name
    if last_name:
        user.last_name = last_name


def list_auth_providers() -> AuthProviderListResponse:
    settings = get_settings()
    providers = enabled_auth_providers()
    is_oidc_configured = oidc_configured(settings)
    return AuthProviderListResponse(
        defaultProvider=settings.auth_default_provider,
        providers=[
            AuthProviderRead(
                provider=provider,
                label=auth_provider_label(provider),
                signInEnabled=provider == "local" or is_oidc_configured,
                signUpEnabled=(
                    provider == "local"
                    or (is_oidc_configured and settings.oidc_auto_create_users)
                ),
            )
            for provider in providers
        ],
    )


async def create_user(
    session: AsyncSession,
    payload: UserCreate,
    *,
    is_superuser: bool = False,
) -> User:
    email = normalize_email(str(payload.email))
    if await repository.get_user_by_email(session, email):
        raise DuplicateUserError("email already exists")

    user = User(
        email=email,
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        is_active=True,
        is_superuser=is_superuser,
    )
    user.local_credentials = LocalAuthCredential(
        password_hash=hash_password(payload.password.get_secret_value()),
        password_updated_at=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()
    return user


async def authenticate_oidc_identity(
    session: AsyncSession,
    oidc_identity: OIDCIdentity,
    *,
    auto_create_users: bool,
    superuser_emails: list[str],
) -> User:
    email = normalize_email(oidc_identity.email)
    promote_to_superuser = email in {
        normalize_email(superuser_email) for superuser_email in superuser_emails
    }
    identity_provider = oidc_identity_provider_key(oidc_identity.issuer)
    identity = await repository.get_external_identity(
        session,
        identity_provider,
        oidc_identity.subject,
    )
    if identity is not None:
        user = identity.user
        if not user.is_active:
            raise OIDCAuthenticationError("user is inactive")
        if normalize_email(user.email) != email:
            conflicting_user = await repository.get_user_by_email(session, email)
            if conflicting_user is not None and conflicting_user.id != user.id:
                raise OIDCAuthenticationError(
                    "OIDC email address is already linked to another user"
                )
            user.email = email
        identity.email = email
        apply_oidc_profile(user, oidc_identity)
        if promote_to_superuser:
            user.is_superuser = True
        user.last_login_at = datetime.now(UTC)
        await session.flush()
        return user

    user = await repository.get_user_by_email(session, email, for_update=True)
    if user is None:
        if not auto_create_users:
            raise OIDCAuthenticationError("OIDC user auto-creation is disabled")
        user = User(
            email=email,
            first_name=oidc_identity.first_name.strip(),
            last_name=oidc_identity.last_name.strip(),
            is_active=True,
            is_superuser=promote_to_superuser,
        )
        session.add(user)
        await session.flush()
    elif not user.is_active:
        raise OIDCAuthenticationError("user is inactive")
    else:
        existing_provider_identity = await repository.get_user_external_identity_for_provider(
            session,
            user.id,
            identity_provider,
        )
        if (
            existing_provider_identity is not None
            and existing_provider_identity.subject != oidc_identity.subject
        ):
            raise OIDCAuthenticationError(
                "OIDC email address is already linked to another identity"
            )
        apply_oidc_profile(user, oidc_identity)
        if promote_to_superuser:
            user.is_superuser = True

    identity = UserExternalIdentity(
        user_id=user.id,
        provider=identity_provider,
        subject=oidc_identity.subject,
        email=email,
    )
    session.add(identity)
    user.last_login_at = datetime.now(UTC)
    await session.flush()
    return user


async def bootstrap_superuser(session: AsyncSession, payload: UserCreate) -> User:
    if await repository.count_users(session) > 0:
        raise BootstrapUserExistsError("bootstrap user already exists")
    user = await create_user(session, payload, is_superuser=True)
    await session.commit()
    await session.refresh(user)
    return user


async def list_users(session: AsyncSession) -> list[User]:
    return await repository.list_users(session)


async def update_user_admin_flags(
    session: AsyncSession,
    actor: User,
    user_id: uuid.UUID,
    payload: UserAdminUpdate,
) -> User:
    user = await repository.get_user_by_id(session, user_id)
    if user is None:
        raise UserNotFoundError("user not found")

    if user.id == actor.id:
        if payload.is_active is False:
            raise InvalidUserRoleUpdateError("you cannot deactivate your own account")
        if payload.is_superuser is False:
            raise InvalidUserRoleUpdateError("you cannot remove your own superuser access")

    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.is_superuser is not None:
        user.is_superuser = payload.is_superuser
    if payload.is_global_moderator is not None:
        user.is_global_moderator = payload.is_global_moderator
    if payload.is_global_partner_manager is not None:
        user.is_global_partner_manager = payload.is_global_partner_manager

    await session.flush()
    await session.refresh(user)
    return user


async def authenticate_local_user(session: AsyncSession, payload: LoginRequest) -> User:
    user = await repository.get_user_by_email(session, normalize_email(str(payload.email)))
    if user is None or user.local_credentials is None or not user.is_active:
        raise InvalidLoginError("invalid email or password")
    if not verify_password(
        payload.password.get_secret_value(),
        user.local_credentials.password_hash,
    ):
        raise InvalidLoginError("invalid email or password")
    user.last_login_at = datetime.now(UTC)
    await session.flush()
    return user


async def create_user_api_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    payload: UserAPITokenCreate,
) -> tuple[UserAPIToken, str]:
    user = await repository.get_user_by_id(session, user_id)
    if user is None:
        raise UserNotFoundError("user not found")
    validate_api_token_scopes(user, payload.scopes)

    token_prefix, token = generate_api_token()
    record = UserAPIToken(
        user_id=user.id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        token_prefix=token_prefix,
        token_hash=hash_api_token(token),
        scopes=unique_scope_strings(payload.scopes),
        organization_ids=unique_uuid_strings(payload.organization_ids),
        is_active=True,
        expires_at=payload.expires_at,
    )
    session.add(record)
    await session.flush()
    return record, token


async def list_user_api_tokens(session: AsyncSession, user_id: uuid.UUID) -> list[UserAPIToken]:
    return await repository.list_user_api_tokens(session, user_id)


async def update_user_api_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    token_id: uuid.UUID,
    payload: UserAPITokenUpdate,
) -> UserAPIToken:
    user = await repository.get_user_by_id(session, user_id)
    if user is None:
        raise UserNotFoundError("user not found")
    token = await repository.get_user_api_token_by_id(session, user_id, token_id)
    if token is None:
        raise UserAPITokenNotFoundError("API token not found")
    if payload.name is not None:
        token.name = payload.name.strip()
    if payload.description is not None:
        token.description = payload.description.strip()
    if payload.scopes is not None:
        validate_api_token_scopes(user, payload.scopes)
        token.scopes = unique_scope_strings(payload.scopes)
    if "expires_at" in payload.model_fields_set:
        token.expires_at = payload.expires_at
    if payload.organization_ids is not None:
        token.organization_ids = unique_uuid_strings(payload.organization_ids)
    if payload.is_active is not None:
        token.is_active = payload.is_active
    await session.flush()
    return token


async def rotate_user_api_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    token_id: uuid.UUID,
) -> tuple[UserAPIToken, str]:
    token = await repository.get_user_api_token_by_id(session, user_id, token_id)
    if token is None:
        raise UserAPITokenNotFoundError("API token not found")

    token_prefix, plaintext_token = generate_api_token()
    token.token_prefix = token_prefix
    token.token_hash = hash_api_token(plaintext_token)
    token.last_used_at = None
    await session.flush()
    return token, plaintext_token


async def delete_user_api_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    token_id: uuid.UUID,
) -> None:
    deleted = await repository.delete_user_api_token(session, user_id, token_id)
    if not deleted:
        raise UserAPITokenNotFoundError("API token not found")


def is_token_expired(token: UserAPIToken, *, now: datetime | None = None) -> bool:
    if token.expires_at is None:
        return False
    return token.expires_at <= (now or datetime.now(UTC))


def is_token_active(token: UserAPIToken, plaintext_token: str) -> bool:
    return token.is_active and not is_token_expired(token) and verify_api_token(
        plaintext_token,
        token.token_hash,
    )


async def authenticate_api_token(
    session: AsyncSession,
    plaintext_token: str,
) -> tuple[User, UserAPIToken] | None:
    token_prefix = extract_api_token_key(plaintext_token)
    if not token_prefix:
        return None
    api_token = await repository.get_api_token_by_prefix(session, token_prefix)
    if api_token is None or not is_token_active(api_token, plaintext_token):
        return None
    user = await repository.get_user_by_id(session, api_token.user_id)
    if user is None or not user.is_active:
        return None
    api_token.last_used_at = datetime.now(UTC)
    await session.flush()
    return user, api_token
