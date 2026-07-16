import time
from urllib.parse import parse_qs, urlparse

import pytest
from joserfc import jwk, jwt

from app.core.config import Settings
from app.modules.users import oidc
from app.modules.users.exceptions import OIDCAuthenticationError, OIDCConfigurationError


def oidc_settings(**overrides) -> Settings:
    values = {
        "auth_providers": ["oidc"],
        "auth_default_provider": "oidc",
        "session_secret": "test-session-secret",
        "registry_public_base_url": "https://hub.example.com",
        "oidc_issuer_url": "https://issuer.example.com",
        "oidc_client_id": "wardn-hub-client",
        "oidc_client_secret": "wardn-hub-secret",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def signed_id_token(
    settings: Settings,
    signing_key,
    *,
    nonce: str = "nonce-1",
    **claim_overrides,
) -> str:
    claims = {
        "iss": oidc.issuer_url(settings),
        "sub": "subject-1",
        "aud": settings.oidc_client_id,
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "nonce": nonce,
        "email": "Admin@Example.COM",
        "email_verified": True,
        "given_name": "Ada",
        "family_name": "Lovelace",
    }
    claims.update(claim_overrides)
    return jwt.encode(
        {"alg": "RS256", "kid": "test-key"},
        claims,
        signing_key,
    )


def test_oidc_state_round_trip() -> None:
    settings = oidc_settings()

    state, cookie = oidc.create_oidc_state(settings, redirect_to="/submissions/123")

    verified = oidc.verify_oidc_state(settings, cookie, state.state)
    assert verified.state == state.state
    assert verified.nonce == state.nonce
    assert verified.redirect_to == "/submissions/123"


@pytest.mark.parametrize("supplied_state", ["wrong-state", ""])
def test_oidc_state_rejects_mismatched_state(supplied_state: str) -> None:
    settings = oidc_settings()
    _state, cookie = oidc.create_oidc_state(settings)

    with pytest.raises(OIDCAuthenticationError, match="state"):
        oidc.verify_oidc_state(settings, cookie, supplied_state)


def test_oidc_state_rejects_tampered_cookie() -> None:
    settings = oidc_settings()
    state, cookie = oidc.create_oidc_state(settings)
    payload, signature = cookie.split(".", 1)

    with pytest.raises(OIDCAuthenticationError, match="invalid OIDC state"):
        oidc.verify_oidc_state(settings, f"{payload}x.{signature}", state.state)


def test_oidc_state_rejects_expired_cookie(monkeypatch) -> None:
    settings = oidc_settings()
    monkeypatch.setattr(oidc.time, "time", lambda: 1000)
    state, cookie = oidc.create_oidc_state(settings)
    monkeypatch.setattr(oidc.time, "time", lambda: 1000 + oidc.OIDC_STATE_TTL_SECONDS + 1)

    with pytest.raises(OIDCAuthenticationError, match="expired OIDC state"):
        oidc.verify_oidc_state(settings, cookie, state.state)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "/"),
        ("", "/"),
        ("https://attacker.example/path", "/"),
        ("//attacker.example/path", "/"),
        ("submissions/123", "/"),
        ("/submit?draft=1", "/submit?draft=1"),
    ],
)
def test_safe_redirect_path(value: str | None, expected: str) -> None:
    assert oidc.safe_redirect_path(value) == expected


def test_frontend_redirect_url_never_reinterprets_local_path_as_absolute_url() -> None:
    assert oidc.frontend_redirect_url(
        oidc_settings(),
        "/https://attacker.example",
    ) == "https://hub.example.com/https://attacker.example"


def test_oidc_state_cookie_name_is_keyed_by_state() -> None:
    settings = oidc_settings()

    first = oidc.oidc_state_cookie_name(settings, "first-state")
    second = oidc.oidc_state_cookie_name(settings, "second-state")

    assert first.startswith("wardn_hub_oidc_state_")
    assert second.startswith("wardn_hub_oidc_state_")
    assert first != second
    assert oidc.oidc_state_cookie_name(settings, None) == "wardn_hub_oidc_state"


def test_oidc_redirect_uri_defaults_to_frontend_proxy_callback() -> None:
    assert (
        oidc.oidc_redirect_uri(oidc_settings())
        == "https://hub.example.com/api/auth/oidc/callback"
    )
    assert (
        oidc.oidc_redirect_uri(oidc_settings(oidc_redirect_uri="https://api.example/callback"))
        == "https://api.example/callback"
    )


def test_authorization_url_contains_oidc_security_parameters() -> None:
    settings = oidc_settings(oidc_scopes="email,profile email")
    state = oidc.OIDCState(state="state-1", nonce="nonce-1", redirect_to="/")

    url = oidc.authorization_url(
        settings,
        {"authorization_endpoint": "https://issuer.example.com/authorize"},
        state,
    )
    query = parse_qs(urlparse(url).query)

    assert query == {
        "client_id": ["wardn-hub-client"],
        "redirect_uri": ["https://hub.example.com/api/auth/oidc/callback"],
        "response_type": ["code"],
        "scope": ["openid email profile"],
        "state": ["state-1"],
        "nonce": ["nonce-1"],
    }


def test_authorization_url_preserves_discovered_query_parameters() -> None:
    settings = oidc_settings()
    state = oidc.OIDCState(state="state-1", nonce="nonce-1", redirect_to="/")

    url = oidc.authorization_url(
        settings,
        {"authorization_endpoint": "https://issuer.example.com/authorize?tenant=wardn"},
        state,
    )

    assert parse_qs(urlparse(url).query)["tenant"] == ["wardn"]


def test_oidc_identity_provider_key_is_stable_and_issuer_qualified() -> None:
    first = oidc.oidc_identity_provider_key("https://issuer.example.com/")
    equivalent = oidc.oidc_identity_provider_key("https://issuer.example.com")
    different = oidc.oidc_identity_provider_key("https://another-issuer.example.com")

    assert first == equivalent
    assert first.startswith("oidc:")
    assert len(first) <= 32
    assert different != first


def test_token_endpoint_auth_method_supports_basic_and_post() -> None:
    assert oidc.token_endpoint_auth_method({}) == "client_secret_basic"
    assert (
        oidc.token_endpoint_auth_method(
            {"token_endpoint_auth_methods_supported": ["client_secret_post"]}
        )
        == "client_secret_post"
    )
    with pytest.raises(OIDCConfigurationError, match="compatible client auth method"):
        oidc.token_endpoint_auth_method(
            {"token_endpoint_auth_methods_supported": ["private_key_jwt"]}
        )


def test_oidc_endpoint_urls_require_https_outside_local_environments() -> None:
    local = oidc_settings(environment="local")
    production = oidc_settings(
        environment="production",
        session_secret="s" * 32,
        api_token_secret="t" * 32,
    )

    assert (
        oidc.validate_oidc_endpoint_url(local, "http://identity.local/token", "token")
        == "http://identity.local/token"
    )
    with pytest.raises(OIDCConfigurationError, match="absolute HTTP"):
        oidc.validate_oidc_endpoint_url(local, "/relative/token", "token")
    with pytest.raises(OIDCConfigurationError, match="HTTPS"):
        oidc.validate_oidc_endpoint_url(
            production,
            "http://identity.example.com/token",
            "token",
        )
    with pytest.raises(OIDCConfigurationError, match="invalid|absolute"):
        oidc.validate_oidc_endpoint_url(
            local,
            "http://identity.local/token#fragment",
            "token",
        )


def test_require_oidc_config_reports_hub_environment_names() -> None:
    settings = oidc_settings(
        oidc_issuer_url="",
        oidc_client_id="",
        oidc_client_secret="",
    )

    with pytest.raises(OIDCConfigurationError) as exc_info:
        oidc.require_oidc_config(settings)

    assert "WARDN_HUB_OIDC_ISSUER_URL" in str(exc_info.value)
    assert "WARDN_HUB_OIDC_CLIENT_ID" in str(exc_info.value)
    assert "WARDN_HUB_OIDC_CLIENT_SECRET" in str(exc_info.value)


@pytest.mark.asyncio
async def test_verify_oidc_identity_validates_signed_id_token(monkeypatch) -> None:
    signing_key = jwk.generate_key("RSA", 2048, parameters={"kid": "test-key"})
    settings = oidc_settings()
    metadata = {"jwks_uri": "https://issuer.example.com/jwks"}

    async def fetch_jwks(_metadata):
        return {"keys": [signing_key.as_dict(private=False)]}

    monkeypatch.setattr(oidc, "fetch_jwks", fetch_jwks)

    identity = await oidc.verify_oidc_identity(
        settings,
        metadata,
        {"id_token": signed_id_token(settings, signing_key)},
        nonce="nonce-1",
    )

    assert identity == oidc.OIDCIdentity(
        email="admin@example.com",
        first_name="Ada",
        last_name="Lovelace",
        subject="subject-1",
        issuer="https://issuer.example.com",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claim_overrides", "nonce", "message"),
    [
        ({"iss": "https://wrong.example.com"}, "nonce-1", "issuer"),
        ({"aud": "another-client"}, "nonce-1", "audience"),
        ({"aud": ["wardn-hub-client", "another"], "azp": "another"}, "nonce-1", "party"),
        ({"aud": "wardn-hub-client", "azp": "another"}, "nonce-1", "party"),
        ({"exp": 0}, "nonce-1", "expired"),
        ({"nbf": int(time.time()) + 300}, "nonce-1", "not yet valid"),
        ({"iat": None}, "nonce-1", "iat claim"),
        ({}, "wrong-nonce", "nonce"),
    ],
)
async def test_verify_oidc_identity_rejects_invalid_claims(
    monkeypatch,
    claim_overrides: dict,
    nonce: str,
    message: str,
) -> None:
    signing_key = jwk.generate_key("RSA", 2048, parameters={"kid": "test-key"})
    settings = oidc_settings()

    async def fetch_jwks(_metadata):
        return {"keys": [signing_key.as_dict(private=False)]}

    monkeypatch.setattr(oidc, "fetch_jwks", fetch_jwks)

    with pytest.raises(OIDCAuthenticationError, match=message):
        await oidc.verify_oidc_identity(
            settings,
            {"jwks_uri": "https://issuer.example.com/jwks"},
            {"id_token": signed_id_token(settings, signing_key, **claim_overrides)},
            nonce=nonce,
        )


def test_id_token_claims_require_issue_time() -> None:
    settings = oidc_settings()

    with pytest.raises(OIDCAuthenticationError, match="issue time"):
        oidc._validate_id_token_claims(
            settings,
            {
                "iss": "https://issuer.example.com",
                "sub": "subject-1",
                "aud": "wardn-hub-client",
                "exp": int(time.time()) + 300,
                "nonce": "nonce-1",
            },
            nonce="nonce-1",
        )


def test_oidc_identity_enforces_verified_email_and_domain_policy() -> None:
    claims = {
        "sub": "subject-1",
        "email": "admin@example.com",
        "email_verified": False,
    }

    with pytest.raises(OIDCAuthenticationError, match="not verified"):
        oidc._identity_from_claims(oidc_settings(), claims)

    identity = oidc._identity_from_claims(
        oidc_settings(
            oidc_allow_unverified_email=True,
            oidc_allowed_email_domains=["example.com"],
        ),
        claims,
    )
    assert identity.email == "admin@example.com"

    with pytest.raises(OIDCAuthenticationError, match="domain is not allowed"):
        oidc._identity_from_claims(
            oidc_settings(oidc_allowed_email_domains=["staff.example.com"]),
            {**claims, "email_verified": True},
        )


@pytest.mark.parametrize(
    ("claims", "message"),
    [
        ({"sub": "subject-1", "email": "not-an-email"}, "email address is invalid"),
        (
            {
                "sub": "subject-1",
                "email": "admin@example.com",
                "email_verified": "true",
            },
            "verification claim is invalid",
        ),
        (
            {"sub": 123, "email": "admin@example.com", "email_verified": True},
            "subject is invalid",
        ),
        (
            {"sub": "subject-1", "email": "admin@example.com"},
            "not verified",
        ),
    ],
)
def test_oidc_identity_rejects_malformed_identity_claims(
    claims: dict,
    message: str,
) -> None:
    with pytest.raises(OIDCAuthenticationError, match=message):
        oidc._identity_from_claims(oidc_settings(), claims)


@pytest.mark.asyncio
async def test_verify_oidc_identity_rejects_mismatched_userinfo_subject(monkeypatch) -> None:
    signing_key = jwk.generate_key("RSA", 2048, parameters={"kid": "test-key"})
    settings = oidc_settings()

    async def fetch_jwks(_metadata):
        return {"keys": [signing_key.as_dict(private=False)]}

    async def fetch_userinfo(_metadata, *, access_token):
        assert access_token == "access-token"
        return {"sub": "different-subject"}

    monkeypatch.setattr(oidc, "fetch_jwks", fetch_jwks)
    monkeypatch.setattr(oidc, "fetch_oidc_userinfo", fetch_userinfo)

    with pytest.raises(OIDCAuthenticationError, match="subject does not match"):
        await oidc.verify_oidc_identity(
            settings,
            {"jwks_uri": "https://issuer.example.com/jwks"},
            {
                "id_token": signed_id_token(settings, signing_key),
                "access_token": "access-token",
            },
            nonce="nonce-1",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("userinfo", "message"),
    [
        ({"email": "other@example.com", "email_verified": True}, "subject does not match"),
        ({"sub": "subject-1", "email": "other@example.com"}, "not verified"),
    ],
)
async def test_verify_oidc_identity_requires_userinfo_subject_and_email_provenance(
    monkeypatch,
    userinfo: dict,
    message: str,
) -> None:
    signing_key = jwk.generate_key("RSA", 2048, parameters={"kid": "test-key"})
    settings = oidc_settings()

    async def fetch_jwks(_metadata):
        return {"keys": [signing_key.as_dict(private=False)]}

    async def fetch_userinfo(_metadata, *, access_token):
        assert access_token == "access-token"
        return userinfo

    monkeypatch.setattr(oidc, "fetch_jwks", fetch_jwks)
    monkeypatch.setattr(oidc, "fetch_oidc_userinfo", fetch_userinfo)

    with pytest.raises(OIDCAuthenticationError, match=message):
        await oidc.verify_oidc_identity(
            settings,
            {"jwks_uri": "https://issuer.example.com/jwks"},
            {
                "id_token": signed_id_token(settings, signing_key),
                "access_token": "access-token",
            },
            nonce="nonce-1",
        )
