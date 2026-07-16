from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.modules.users import dependencies
from app.modules.users.models import User


def request_with_cookie(name: str, value: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/me",
            "query_string": b"",
            "headers": [(b"cookie", f"{name}={value}".encode())],
        }
    )


@pytest.mark.asyncio
async def test_current_user_preserves_api_token_bearer_auth(monkeypatch) -> None:
    user = User(email="member@example.com", is_active=True)
    user.id = uuid4()
    api_token = SimpleNamespace(scopes=["catalog:read"])
    captured_token = ""
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(session_cookie_name="wardn_hub_session"),
    )

    async def authenticate(_session, plaintext_token):
        nonlocal captured_token
        captured_token = plaintext_token
        return user, api_token

    monkeypatch.setattr(dependencies, "authenticate_api_token", authenticate)
    request = Request({"type": "http", "headers": []})

    result = await dependencies.get_current_user(request, object(), "bEaReR api-secret")

    assert result is user
    assert captured_token == "api-secret"
    assert dependencies.get_request_api_token(request) is api_token


@pytest.mark.asyncio
async def test_current_user_uses_hub_session_cookie(monkeypatch) -> None:
    user = User(email="member@example.com", is_active=True)
    user.id = uuid4()
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(session_cookie_name="wardn_hub_session"),
    )
    monkeypatch.setattr(dependencies, "verify_session_token", lambda token: user.id)

    async def get_user(_session, user_id):
        assert user_id == user.id
        return user

    monkeypatch.setattr(dependencies.repository, "get_user_by_id", get_user)

    result = await dependencies.get_current_user(
        request_with_cookie("wardn_hub_session", "signed-session"),
        object(),
    )

    assert result is user


@pytest.mark.asyncio
async def test_current_user_rejects_unknown_bearer_token(monkeypatch) -> None:
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(session_cookie_name="wardn_hub_session"),
    )

    async def missing_token(_session, _plaintext_token):
        return None

    monkeypatch.setattr(dependencies, "authenticate_api_token", missing_token)

    with pytest.raises(HTTPException) as exc_info:
        await dependencies.get_current_user(
            Request({"type": "http", "headers": []}),
            object(),
            "Bearer former-external-token",
        )

    assert exc_info.value.status_code == 401
