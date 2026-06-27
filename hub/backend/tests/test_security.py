from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.security import (
    create_session_token,
    extract_api_token_key,
    generate_api_token,
    hash_api_token,
    verify_api_token,
    verify_session_token,
)
from app.db.session import get_db_session
from app.main import create_app
from app.modules.users import dependencies


def test_api_token_generation_and_verification() -> None:
    key, token = generate_api_token()

    assert extract_api_token_key(token) == key
    assert verify_api_token(token, hash_api_token(token)) is True
    assert verify_api_token(f"{token}x", hash_api_token(token)) is False


def test_session_token_round_trip() -> None:
    user_id = uuid4()

    token = create_session_token(user_id)

    assert verify_session_token(token) == user_id
    assert verify_session_token(f"{token}x") is None


def test_api_token_management_requires_token_scope(monkeypatch) -> None:
    app = create_app()

    async def fake_session():
        yield object()

    async def authenticate_api_token(*args, **kwargs):
        return (
            object(),
            type("Token", (), {"scopes": ["catalog:read", "submissions:read"]})(),
        )

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(dependencies, "authenticate_api_token", authenticate_api_token)

    response = TestClient(app).get(
        "/api/v1/auth/api-tokens",
        headers={"Authorization": "Bearer wardn_hub_key.secret"},
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "API token missing required scope: tokens:read",
    }


@pytest.mark.parametrize(
    ("method", "path", "json_body", "user_flags", "required_scope"),
    [
        (
            "GET",
            "/api/v1/audit/events",
            None,
            {"is_superuser": True},
            "audit:read",
        ),
        (
            "POST",
            "/api/v1/mcp/categories",
            {"slug": "automation", "name": "Automation"},
            {"is_superuser": True},
            "registry:write",
        ),
        (
            "PATCH",
            "/api/v1/admin/mcp/servers/io.github.example/weather/versions/1.0.0/quality-score",
            {"qualityScore": 96},
            {"is_superuser": True},
            "registry:score",
        ),
        (
            "POST",
            f"/api/v1/submissions/{uuid4()}/approve",
            None,
            {"is_global_moderator": True},
            "submissions:moderate",
        ),
        (
            "POST",
            f"/api/v1/submissions/{uuid4()}/publish",
            None,
            {"is_superuser": True},
            "submissions:publish",
        ),
        (
            "PATCH",
            f"/api/v1/partners/organizations/{uuid4()}",
            {},
            {"is_global_partner_manager": True},
            "partners:write",
        ),
        (
            "GET",
            "/api/v1/users",
            None,
            {"is_superuser": True},
            "users:read",
        ),
        (
            "PATCH",
            f"/api/v1/users/{uuid4()}",
            {"isGlobalModerator": True},
            {"is_superuser": True},
            "users:write",
        ),
    ],
)
def test_privileged_routes_require_matching_api_token_scope(
    monkeypatch,
    method: str,
    path: str,
    json_body: dict | None,
    user_flags: dict[str, bool],
    required_scope: str,
) -> None:
    app = create_app()

    async def fake_session():
        yield object()

    async def authenticate_api_token(*args, **kwargs):
        user_attrs = {
            "is_active": True,
            "is_superuser": False,
            "is_global_moderator": False,
            "is_global_partner_manager": False,
        }
        user_attrs.update(user_flags)
        user = SimpleNamespace(
            **user_attrs,
        )
        token = SimpleNamespace(scopes=["catalog:read", "submissions:read", "submissions:write"])
        return user, token

    app.dependency_overrides[get_db_session] = fake_session
    monkeypatch.setattr(dependencies, "authenticate_api_token", authenticate_api_token)

    response = TestClient(app).request(
        method,
        path,
        headers={"Authorization": "Bearer wardn_hub_key.secret"},
        json=json_body,
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": f"API token missing required scope: {required_scope}",
    }
