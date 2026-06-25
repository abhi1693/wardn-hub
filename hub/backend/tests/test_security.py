from uuid import uuid4

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
