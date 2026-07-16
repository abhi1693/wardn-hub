import hashlib
import hmac
import json
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import httpx
from email_validator import EmailNotValidError, validate_email
from joserfc import jwk, jwt
from joserfc.errors import JoseError

from app.core.config import LOCAL_ENVIRONMENTS, Settings
from app.modules.users.exceptions import OIDCAuthenticationError, OIDCConfigurationError

OIDC_STATE_TTL_SECONDS = 10 * 60
OIDC_CLAIMS_LEEWAY_SECONDS = 60
OIDC_ALLOWED_ID_TOKEN_ALGORITHMS = (
    "RS256",
    "RS384",
    "RS512",
    "ES256",
    "ES384",
    "ES512",
)


@dataclass(frozen=True)
class OIDCState:
    state: str
    nonce: str
    redirect_to: str


@dataclass(frozen=True)
class OIDCIdentity:
    email: str
    first_name: str
    last_name: str
    subject: str
    issuer: str


def _base64url_encode(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return urlsafe_b64decode(f"{data}{padding}".encode("ascii"))


def oidc_enabled(settings: Settings) -> bool:
    return "oidc" in settings.auth_providers


def oidc_configured(settings: Settings) -> bool:
    return all(
        value.strip()
        for value in (
            settings.oidc_issuer_url,
            settings.oidc_client_id,
            settings.oidc_client_secret,
        )
    )


def require_oidc_config(settings: Settings) -> None:
    missing = [
        name
        for name, value in {
            "WARDN_HUB_OIDC_ISSUER_URL": settings.oidc_issuer_url,
            "WARDN_HUB_OIDC_CLIENT_ID": settings.oidc_client_id,
            "WARDN_HUB_OIDC_CLIENT_SECRET": settings.oidc_client_secret,
        }.items()
        if not value.strip()
    ]
    if missing:
        raise OIDCConfigurationError(f"missing OIDC configuration: {', '.join(missing)}")
    validate_oidc_endpoint_url(
        settings,
        settings.oidc_issuer_url,
        "issuer",
        allow_query=False,
    )
    validate_oidc_endpoint_url(
        settings,
        settings.registry_public_base_url,
        "frontend",
        allow_query=False,
    )
    oidc_redirect_uri(settings)


def validate_oidc_endpoint_url(
    settings: Settings,
    value: Any,
    name: str,
    *,
    allow_query: bool = True,
) -> str:
    if not isinstance(value, str):
        raise OIDCConfigurationError(f"OIDC {name} URL is invalid")
    parsed = urlparse(value.strip())
    allowed_schemes = (
        {"http", "https"} if settings.environment in LOCAL_ENVIRONMENTS else {"https"}
    )
    if (
        parsed.scheme not in allowed_schemes
        or not parsed.netloc
        or not parsed.hostname
        or parsed.fragment
        or (not allow_query and parsed.query)
    ):
        requirement = "absolute HTTP(S)" if settings.environment in LOCAL_ENVIRONMENTS else "HTTPS"
        raise OIDCConfigurationError(f"OIDC {name} URL must be an absolute {requirement} URL")
    return value.strip()


def issuer_url(settings: Settings) -> str:
    return settings.oidc_issuer_url.strip().rstrip("/")


def oidc_identity_provider_key(issuer: str) -> str:
    normalized_issuer = issuer.strip().rstrip("/")
    if not normalized_issuer:
        raise OIDCAuthenticationError("OIDC identity issuer is invalid")
    digest = hashlib.sha256(normalized_issuer.encode("utf-8")).hexdigest()[:24]
    return f"oidc:{digest}"


def oidc_redirect_uri(settings: Settings) -> str:
    if settings.oidc_redirect_uri.strip():
        redirect_uri = settings.oidc_redirect_uri.strip()
    else:
        frontend_base_url = validate_oidc_endpoint_url(
            settings,
            settings.registry_public_base_url,
            "frontend",
            allow_query=False,
        )
        redirect_uri = urljoin(
            frontend_base_url.rstrip("/") + "/",
            "api/auth/oidc/callback",
        )
    return validate_oidc_endpoint_url(
        settings,
        redirect_uri,
        "redirect",
    )


def oidc_scopes(settings: Settings) -> str:
    scopes = [scope for scope in settings.oidc_scopes.replace(",", " ").split() if scope]
    if "openid" not in scopes:
        scopes.insert(0, "openid")
    return " ".join(dict.fromkeys(scopes))


def token_endpoint_auth_method(metadata: dict[str, Any]) -> str:
    supported = metadata.get("token_endpoint_auth_methods_supported")
    if supported is None:
        return "client_secret_basic"
    if not isinstance(supported, list) or not all(isinstance(value, str) for value in supported):
        raise OIDCConfigurationError(
            "OIDC discovery token_endpoint_auth_methods_supported is invalid"
        )
    for method in ("client_secret_basic", "client_secret_post"):
        if method in supported:
            return method
    raise OIDCConfigurationError("OIDC provider does not support a compatible client auth method")


def safe_redirect_path(value: str | None) -> str:
    if not value:
        return "/"
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/"):
        return "/"
    return value


def frontend_redirect_url(settings: Settings, path: str) -> str:
    frontend_base_url = validate_oidc_endpoint_url(
        settings,
        settings.registry_public_base_url,
        "frontend",
        allow_query=False,
    )
    return f"{frontend_base_url.rstrip('/')}{safe_redirect_path(path)}"


def oidc_state_cookie_name(settings: Settings, state: str | None) -> str:
    if not state:
        return settings.oidc_state_cookie_name
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()[:24]
    return f"{settings.oidc_state_cookie_name}_{digest}"


def create_oidc_state(
    settings: Settings,
    *,
    redirect_to: str | None = None,
) -> tuple[OIDCState, str]:
    state = OIDCState(
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(32),
        redirect_to=safe_redirect_path(redirect_to),
    )
    payload = {
        "state": state.state,
        "nonce": state.nonce,
        "redirectTo": state.redirect_to,
        "exp": int(time.time()) + OIDC_STATE_TTL_SECONDS,
    }
    payload_data = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(
        settings.session_secret.encode(),
        payload_data.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return state, f"{payload_data}.{_base64url_encode(signature)}"


def verify_oidc_state(settings: Settings, token: str, supplied_state: str) -> OIDCState:
    try:
        payload_data, signature_data = token.split(".", 1)
        expected_signature = hmac.new(
            settings.session_secret.encode(),
            payload_data.encode("ascii"),
            hashlib.sha256,
        ).digest()
        supplied_signature = _base64url_decode(signature_data)
        if not hmac.compare_digest(expected_signature, supplied_signature):
            raise OIDCAuthenticationError("invalid OIDC state")

        payload = json.loads(_base64url_decode(payload_data))
        if int(payload["exp"]) < int(time.time()):
            raise OIDCAuthenticationError("expired OIDC state")
        if not hmac.compare_digest(str(payload["state"]), supplied_state):
            raise OIDCAuthenticationError("mismatched OIDC state")
        return OIDCState(
            state=str(payload["state"]),
            nonce=str(payload["nonce"]),
            redirect_to=safe_redirect_path(str(payload.get("redirectTo") or "/")),
        )
    except OIDCAuthenticationError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OIDCAuthenticationError("invalid OIDC state") from exc


async def fetch_oidc_metadata(settings: Settings) -> dict[str, Any]:
    require_oidc_config(settings)
    url = f"{issuer_url(settings)}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, headers={"accept": "application/json"})
            response.raise_for_status()
        metadata = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OIDCConfigurationError("OIDC discovery request failed") from exc
    if not isinstance(metadata, dict):
        raise OIDCConfigurationError("OIDC discovery document is invalid")

    discovered_issuer = str(metadata.get("issuer", "")).rstrip("/")
    if discovered_issuer != issuer_url(settings):
        raise OIDCConfigurationError("OIDC discovery issuer does not match configured issuer")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not metadata.get(key):
            raise OIDCConfigurationError(f"OIDC discovery document is missing {key}")
        metadata[key] = validate_oidc_endpoint_url(settings, metadata[key], key)
    if metadata.get("userinfo_endpoint"):
        metadata["userinfo_endpoint"] = validate_oidc_endpoint_url(
            settings,
            metadata["userinfo_endpoint"],
            "userinfo_endpoint",
        )
    token_endpoint_auth_method(metadata)
    return metadata


def authorization_url(
    settings: Settings,
    metadata: dict[str, Any],
    state: OIDCState,
) -> str:
    params = {
        "client_id": settings.oidc_client_id,
        "redirect_uri": oidc_redirect_uri(settings),
        "response_type": "code",
        "scope": oidc_scopes(settings),
        "state": state.state,
        "nonce": state.nonce,
    }
    authorization_endpoint = str(metadata["authorization_endpoint"])
    separator = "&" if urlparse(authorization_endpoint).query else "?"
    return f"{authorization_endpoint}{separator}{urlencode(params)}"


async def exchange_oidc_code(
    settings: Settings,
    metadata: dict[str, Any],
    *,
    code: str,
) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": oidc_redirect_uri(settings),
    }
    method = token_endpoint_auth_method(metadata)
    auth: tuple[str, str] | None = None
    if method == "client_secret_basic":
        auth = (settings.oidc_client_id, settings.oidc_client_secret)
    else:
        data.update(
            {
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret,
            }
        )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                str(metadata["token_endpoint"]),
                data=data,
                auth=auth,
                headers={"accept": "application/json"},
            )
    except (httpx.HTTPError, KeyError) as exc:
        raise OIDCAuthenticationError("OIDC code exchange failed") from exc
    if response.status_code >= 400:
        raise OIDCAuthenticationError("OIDC code exchange failed")
    try:
        token_response = response.json()
    except ValueError as exc:
        raise OIDCAuthenticationError("OIDC token response is invalid") from exc
    if not isinstance(token_response, dict):
        raise OIDCAuthenticationError("OIDC token response is invalid")
    if not token_response.get("id_token"):
        raise OIDCAuthenticationError("OIDC token response did not include an ID token")
    return token_response


async def fetch_jwks(metadata: dict[str, Any]) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                str(metadata["jwks_uri"]),
                headers={"accept": "application/json"},
            )
            response.raise_for_status()
        key_set = response.json()
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise OIDCAuthenticationError("OIDC JWKS request failed") from exc
    if not isinstance(key_set, dict):
        raise OIDCAuthenticationError("OIDC JWKS response is invalid")
    return key_set


def _validate_id_token_claims(settings: Settings, claims: dict[str, Any], *, nonce: str) -> None:
    now = int(time.time())

    def int_claim(name: str, default: int | None = None) -> int:
        value = claims.get(name, default)
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise OIDCAuthenticationError(f"OIDC ID token {name} claim is invalid") from exc

    if str(claims.get("iss", "")).rstrip("/") != issuer_url(settings):
        raise OIDCAuthenticationError("OIDC ID token issuer is invalid")

    audience = claims.get("aud")
    if isinstance(audience, str):
        audiences = [audience]
    elif isinstance(audience, list):
        audiences = [str(value) for value in audience]
    else:
        raise OIDCAuthenticationError("OIDC ID token audience is invalid")
    if settings.oidc_client_id not in audiences:
        raise OIDCAuthenticationError("OIDC ID token audience is invalid")
    authorized_party = claims.get("azp")
    if len(audiences) > 1 and authorized_party is None:
        raise OIDCAuthenticationError("OIDC ID token authorized party is invalid")
    if authorized_party is not None and authorized_party != settings.oidc_client_id:
        raise OIDCAuthenticationError("OIDC ID token authorized party is invalid")

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise OIDCAuthenticationError("OIDC ID token subject is missing")
    if int_claim("exp", 0) < now - OIDC_CLAIMS_LEEWAY_SECONDS:
        raise OIDCAuthenticationError("OIDC ID token is expired")
    if "nbf" in claims and int_claim("nbf") > now + OIDC_CLAIMS_LEEWAY_SECONDS:
        raise OIDCAuthenticationError("OIDC ID token is not yet valid")
    if "iat" not in claims or int_claim("iat") > now + OIDC_CLAIMS_LEEWAY_SECONDS:
        raise OIDCAuthenticationError("OIDC ID token issue time is invalid")
    if claims.get("nonce") != nonce:
        raise OIDCAuthenticationError("OIDC ID token nonce is invalid")


def _names_from_claims(claims: dict[str, Any]) -> tuple[str, str]:
    first_name = str(claims.get("given_name") or "").strip()
    last_name = str(claims.get("family_name") or "").strip()
    if first_name or last_name:
        return first_name, last_name

    name = str(claims.get("name") or "").strip()
    if not name:
        return "", ""
    first, _, rest = name.partition(" ")
    return first.strip(), rest.strip()


def _identity_from_claims(settings: Settings, claims: dict[str, Any]) -> OIDCIdentity:
    raw_email = claims.get("email")
    if not isinstance(raw_email, str) or not raw_email.strip():
        raise OIDCAuthenticationError("OIDC identity did not include an email address")
    try:
        email = validate_email(raw_email.strip(), check_deliverability=False).normalized.casefold()
    except EmailNotValidError as exc:
        raise OIDCAuthenticationError("OIDC identity email address is invalid") from exc

    email_verified = claims.get("email_verified")
    if email_verified is not None and not isinstance(email_verified, bool):
        raise OIDCAuthenticationError("OIDC email verification claim is invalid")
    if email_verified is not True and not settings.oidc_allow_unverified_email:
        raise OIDCAuthenticationError("OIDC email address is not verified")

    _, _, domain = email.rpartition("@")
    allowed_domains = {
        value.casefold().removeprefix("@") for value in settings.oidc_allowed_email_domains
    }
    if allowed_domains and domain.casefold() not in allowed_domains:
        raise OIDCAuthenticationError("OIDC email domain is not allowed")

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject or len(subject) > 255:
        raise OIDCAuthenticationError("OIDC identity subject is invalid")

    first_name, last_name = _names_from_claims(claims)
    return OIDCIdentity(
        email=email,
        first_name=first_name[:150],
        last_name=last_name[:150],
        subject=subject,
        issuer=issuer_url(settings),
    )


async def fetch_oidc_userinfo(
    metadata: dict[str, Any],
    *,
    access_token: str | None,
) -> dict[str, Any] | None:
    userinfo_endpoint = metadata.get("userinfo_endpoint")
    if not userinfo_endpoint or not access_token:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                str(userinfo_endpoint),
                headers={
                    "accept": "application/json",
                    "authorization": f"Bearer {access_token}",
                },
            )
    except httpx.HTTPError as exc:
        raise OIDCAuthenticationError("OIDC userinfo request failed") from exc
    if response.status_code >= 400:
        raise OIDCAuthenticationError("OIDC userinfo request failed")
    try:
        userinfo = response.json()
    except ValueError as exc:
        raise OIDCAuthenticationError("OIDC userinfo response is invalid") from exc
    if not isinstance(userinfo, dict):
        raise OIDCAuthenticationError("OIDC userinfo response is invalid")
    return userinfo


async def verify_oidc_identity(
    settings: Settings,
    metadata: dict[str, Any],
    token_response: dict[str, Any],
    *,
    nonce: str,
) -> OIDCIdentity:
    key_set_data = await fetch_jwks(metadata)
    try:
        key_set = jwk.KeySet.import_key_set(key_set_data)
        token = jwt.decode(
            str(token_response["id_token"]),
            key_set,
            algorithms=OIDC_ALLOWED_ID_TOKEN_ALGORITHMS,
        )
    except (JoseError, KeyError, TypeError, ValueError) as exc:
        raise OIDCAuthenticationError("OIDC ID token validation failed") from exc

    claims = dict(token.claims)
    _validate_id_token_claims(settings, claims, nonce=nonce)

    userinfo = await fetch_oidc_userinfo(
        metadata,
        access_token=token_response.get("access_token"),
    )
    if userinfo is not None:
        userinfo_subject = userinfo.get("sub")
        if not isinstance(userinfo_subject, str) or userinfo_subject != claims.get("sub"):
            raise OIDCAuthenticationError("OIDC userinfo subject does not match ID token")
        id_token_email = str(claims.get("email") or "").strip().casefold()
        userinfo_email = str(userinfo.get("email") or "").strip().casefold()
        if userinfo_email and userinfo_email != id_token_email and "email_verified" not in userinfo:
            claims.pop("email_verified", None)
        claims = {**claims, **userinfo}
    return _identity_from_claims(settings, claims)
