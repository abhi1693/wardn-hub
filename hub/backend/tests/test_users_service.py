from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.security import verify_password
from app.modules.users import service
from app.modules.users.exceptions import (
    BootstrapUserExistsError,
    DuplicateUserError,
    InvalidLoginError,
)
from app.modules.users.schemas import LoginRequest, UserCreate


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False
        self.flushed = False

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushed = True
        now = datetime(2026, 6, 23, tzinfo=UTC)
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()
            if getattr(instance, "created_at", None) is None:
                instance.created_at = now
            if getattr(instance, "updated_at", None) is None:
                instance.updated_at = now

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, instance) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = uuid4()


def user_payload() -> UserCreate:
    return UserCreate(
        email="ADMIN@EXAMPLE.COM",
        password="correct horse battery staple",
        first_name="Admin",
        last_name="User",
    )


@pytest.mark.asyncio
async def test_create_user_normalizes_email_and_hashes_password(monkeypatch) -> None:
    async def missing_user(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_user_by_email", missing_user)

    user = await service.create_user(FakeSession(), user_payload(), is_superuser=True)

    assert user.email == "admin@example.com"
    assert user.is_superuser is True
    assert user.local_credentials is not None
    assert verify_password(
        "correct horse battery staple",
        user.local_credentials.password_hash,
    )


@pytest.mark.asyncio
async def test_create_user_rejects_duplicate_email(monkeypatch) -> None:
    async def existing_user(*args, **kwargs):
        return object()

    monkeypatch.setattr(service.repository, "get_user_by_email", existing_user)

    with pytest.raises(DuplicateUserError):
        await service.create_user(FakeSession(), user_payload())


@pytest.mark.asyncio
async def test_bootstrap_rejects_second_user(monkeypatch) -> None:
    async def count_users(*args, **kwargs):
        return 1

    monkeypatch.setattr(service.repository, "count_users", count_users)

    with pytest.raises(BootstrapUserExistsError):
        await service.bootstrap_superuser(FakeSession(), user_payload())


@pytest.mark.asyncio
async def test_authenticate_local_user_rejects_bad_password(monkeypatch) -> None:
    async def missing_user(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_user_by_email", missing_user)
    user = await service.create_user(FakeSession(), user_payload(), is_superuser=True)

    async def existing_user(*args, **kwargs):
        return user

    monkeypatch.setattr(service.repository, "get_user_by_email", existing_user)

    with pytest.raises(InvalidLoginError):
        await service.authenticate_local_user(
            FakeSession(),
            LoginRequest(email="admin@example.com", password="wrong-password"),
        )
