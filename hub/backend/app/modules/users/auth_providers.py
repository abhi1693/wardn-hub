from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
import jwt
from jwt import InvalidTokenError, PyJWKClient, PyJWKClientError

from app.core.config import get_settings


@dataclass(frozen=True)
class ExternalIdentityClaims:
    provider: str
    subject: str
    email: str
    first_name: str = ""
    last_name: str = ""


class ExternalAuthError(Exception):
    pass


def enabled_auth_providers() -> list[str]:
    return get_settings().auth_providers


def is_auth_provider_enabled(provider: str) -> bool:
    return provider in enabled_auth_providers()


def require_auth_provider(provider: str) -> None:
    if not is_auth_provider_enabled(provider):
        raise ExternalAuthError(f"{provider} auth is not enabled")


@lru_cache
def clerk_jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url)


def clerk_jwks_url() -> str:
    settings = get_settings()
    if settings.clerk_jwks_url:
        return settings.clerk_jwks_url
    if not settings.clerk_issuer:
        raise ExternalAuthError("clerk_issuer is not configured")
    return f"{settings.clerk_issuer.rstrip('/')}/.well-known/jwks.json"


def string_claim(claims: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


async def fetch_clerk_user_email(subject: str) -> str:
    settings = get_settings()
    if not settings.clerk_secret_key:
        return ""

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"https://api.clerk.com/v1/users/{subject}",
                headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
            )
    except httpx.HTTPError:
        return ""
    if response.status_code >= 400:
        return ""
    try:
        payload = response.json()
    except ValueError:
        return ""
    email_addresses = payload.get("email_addresses")
    primary_email_id = payload.get("primary_email_address_id")
    if not isinstance(email_addresses, list):
        return ""
    for email_record in email_addresses:
        if not isinstance(email_record, dict):
            continue
        if email_record.get("id") == primary_email_id:
            return string_claim(email_record, "email_address")
    return ""


async def verify_clerk_token(token: str) -> ExternalIdentityClaims:
    require_auth_provider("clerk")
    settings = get_settings()
    if not settings.clerk_issuer:
        raise ExternalAuthError("clerk_issuer is not configured")

    try:
        signing_key = clerk_jwks_client(clerk_jwks_url()).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.clerk_audience or None,
            issuer=settings.clerk_issuer,
            options={"verify_aud": bool(settings.clerk_audience)},
        )
    except (InvalidTokenError, PyJWKClientError) as exc:
        raise ExternalAuthError("invalid Clerk token") from exc

    subject = string_claim(claims, "sub")
    if not subject:
        raise ExternalAuthError("Clerk token is missing subject")

    email = string_claim(claims, "email", "email_address")
    if not email:
        email = await fetch_clerk_user_email(subject)
    if not email:
        raise ExternalAuthError("Clerk token did not provide an email")

    return ExternalIdentityClaims(
        provider="clerk",
        subject=subject,
        email=email,
        first_name=string_claim(claims, "given_name", "first_name"),
        last_name=string_claim(claims, "family_name", "last_name"),
    )


async def verify_external_bearer_token(token: str) -> ExternalIdentityClaims | None:
    if is_auth_provider_enabled("clerk"):
        try:
            return await verify_clerk_token(token)
        except ExternalAuthError:
            return None
    return None
