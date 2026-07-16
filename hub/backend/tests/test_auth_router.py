from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.modules.users import auth_router
from app.modules.users.models import User
from app.modules.users.oidc import OIDCIdentity, OIDCState, oidc_state_cookie_name


class FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


def oidc_settings(**overrides):
    values = {
        "auth_providers": ["oidc"],
        "auth_default_provider": "oidc",
        "environment": "local",
        "registry_public_base_url": "https://hub.example.com",
        "session_cookie_name": "wardn_hub_session",
        "session_secret": "test-session-secret",
        "session_ttl_seconds": 43200,
        "oidc_provider_name": "Example SSO",
        "oidc_issuer_url": "https://issuer.example.com",
        "oidc_client_id": "wardn-hub-client",
        "oidc_client_secret": "wardn-hub-secret",
        "oidc_redirect_uri": "",
        "oidc_scopes": "openid email profile",
        "oidc_state_cookie_name": "wardn_hub_oidc_state",
        "oidc_auto_create_users": True,
        "oidc_superuser_emails": ["admin@example.com"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def request_with_cookie(name: str, value: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/oidc/callback",
            "query_string": b"",
            "headers": [(b"cookie", f"{name}={value}".encode())],
        }
    )


@pytest.mark.asyncio
async def test_oidc_login_redirects_and_sets_keyed_state_cookie(monkeypatch) -> None:
    settings = oidc_settings()
    monkeypatch.setattr(auth_router, "get_settings", lambda: settings)

    async def metadata(_settings):
        return {
            "authorization_endpoint": "https://issuer.example.com/authorize",
            "token_endpoint": "https://issuer.example.com/token",
            "jwks_uri": "https://issuer.example.com/jwks",
        }

    monkeypatch.setattr(auth_router, "fetch_oidc_metadata", metadata)

    response = await auth_router.oidc_login(redirect_to="/submissions/123")

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://issuer.example.com/authorize?")
    set_cookie_headers = response.headers.getlist("set-cookie")
    assert any("wardn_hub_oidc_state_" in header for header in set_cookie_headers)
    assert any("HttpOnly" in header and "Max-Age=600" in header for header in set_cookie_headers)


@pytest.mark.asyncio
async def test_oidc_login_returns_not_found_when_provider_is_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        auth_router,
        "get_settings",
        lambda: oidc_settings(auth_providers=["local"], auth_default_provider="local"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await auth_router.oidc_login()

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("redirect_to", "expected_location"),
    [
        ("/submit", "https://hub.example.com/submit"),
        (
            "/https://attacker.example",
            "https://hub.example.com/https://attacker.example",
        ),
    ],
)
async def test_oidc_callback_mints_hub_session_and_clears_state(
    monkeypatch,
    redirect_to: str,
    expected_location: str,
) -> None:
    settings = oidc_settings()
    state = "state-1"
    state_cookie_name = oidc_state_cookie_name(settings, state)
    request = request_with_cookie(state_cookie_name, "signed-state")
    session = FakeSession()
    user = User(email="admin@example.com", is_active=True)
    user.id = uuid4()
    identity = OIDCIdentity(
        email="admin@example.com",
        first_name="Admin",
        last_name="User",
        subject="subject-1",
        issuer="https://issuer.example.com",
    )
    monkeypatch.setattr(auth_router, "get_settings", lambda: settings)
    monkeypatch.setattr(auth_router, "create_session_token", lambda _user_id: "hub-session")
    monkeypatch.setattr(
        auth_router,
        "verify_oidc_state",
        lambda *_args: OIDCState(state=state, nonce="nonce-1", redirect_to=redirect_to),
    )

    async def metadata(_settings):
        return {"token_endpoint": "token", "jwks_uri": "jwks"}

    async def exchange(_settings, _metadata, *, code):
        assert code == "authorization-code"
        return {"id_token": "id-token"}

    async def verify(_settings, _metadata, _token_response, *, nonce):
        assert nonce == "nonce-1"
        return identity

    async def authenticate(
        _session,
        supplied_identity,
        *,
        auto_create_users,
        superuser_emails,
    ):
        assert supplied_identity is identity
        assert auto_create_users is True
        assert superuser_emails == ["admin@example.com"]
        return user

    monkeypatch.setattr(auth_router, "fetch_oidc_metadata", metadata)
    monkeypatch.setattr(auth_router, "exchange_oidc_code", exchange)
    monkeypatch.setattr(auth_router, "verify_oidc_identity", verify)
    monkeypatch.setattr(auth_router, "authenticate_oidc_identity", authenticate)

    response = await auth_router.oidc_callback(
        request,
        session,
        code="authorization-code",
        state=state,
    )

    assert response.status_code == 302
    assert response.headers["location"] == expected_location
    assert session.committed is True
    set_cookie_headers = response.headers.getlist("set-cookie")
    assert any("wardn_hub_session=hub-session" in header for header in set_cookie_headers)
    assert any(
        f"{state_cookie_name}=" in header and "Max-Age=0" in header
        for header in set_cookie_headers
    )


@pytest.mark.asyncio
async def test_oidc_callback_provider_error_redirects_and_clears_state(monkeypatch) -> None:
    settings = oidc_settings()
    monkeypatch.setattr(auth_router, "get_settings", lambda: settings)

    response = await auth_router.oidc_callback(
        request_with_cookie("unused", "unused"),
        FakeSession(),
        state="state-1",
        error="access_denied",
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://hub.example.com/login?error=oidc"
    assert any("Max-Age=0" in header for header in response.headers.getlist("set-cookie"))


@pytest.mark.asyncio
async def test_oidc_callback_rejects_missing_code_or_state(monkeypatch) -> None:
    monkeypatch.setattr(auth_router, "get_settings", oidc_settings)

    with pytest.raises(HTTPException) as exc_info:
        await auth_router.oidc_callback(Request({"type": "http", "headers": []}), FakeSession())

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_oidc_callback_rejects_missing_state_cookie(monkeypatch) -> None:
    monkeypatch.setattr(auth_router, "get_settings", oidc_settings)

    with pytest.raises(HTTPException) as exc_info:
        await auth_router.oidc_callback(
            Request({"type": "http", "headers": []}),
            FakeSession(),
            code="code",
            state="state",
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "missing OIDC state"
