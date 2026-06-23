from uuid import uuid4

from app.core.security import (
    create_session_token,
    extract_api_token_key,
    generate_api_token,
    hash_api_token,
    verify_api_token,
    verify_session_token,
)


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

