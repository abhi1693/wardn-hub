from types import SimpleNamespace

import pytest

from app.modules.users import auth_providers
from app.modules.users.auth_providers import ClerkUserProfile


@pytest.mark.asyncio
async def test_verify_clerk_token_merges_profile_names(monkeypatch) -> None:
    monkeypatch.setattr(
        auth_providers,
        "get_settings",
        lambda: SimpleNamespace(
            auth_providers=["clerk"],
            clerk_audience="",
            clerk_issuer="https://clerk.example.test",
            clerk_jwks_url="",
            clerk_secret_key="sk_test",
        ),
    )
    monkeypatch.setattr(
        auth_providers,
        "clerk_jwks_client",
        lambda _url: SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key="public-key")
        ),
    )
    monkeypatch.setattr(
        auth_providers.jwt,
        "decode",
        lambda *_args, **_kwargs: {
            "sub": "user_123",
            "email": "member@example.com",
        },
    )

    async def profile(_subject: str) -> ClerkUserProfile:
        return ClerkUserProfile(first_name="Member", last_name="User")

    monkeypatch.setattr(auth_providers, "fetch_clerk_user_profile", profile)

    claims = await auth_providers.verify_clerk_token("jwt")

    assert claims.provider == "clerk"
    assert claims.subject == "user_123"
    assert claims.email == "member@example.com"
    assert claims.first_name == "Member"
    assert claims.last_name == "User"
