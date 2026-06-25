from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.security import verify_password
from app.modules.users import service
from app.modules.users.auth_providers import ExternalIdentityClaims
from app.modules.users.exceptions import (
    BootstrapUserExistsError,
    DuplicateUserError,
    InvalidLoginError,
    InvalidUserRoleUpdateError,
)
from app.modules.users.models import User, UserExternalIdentity
from app.modules.users.schemas import LoginRequest, UserAdminUpdate, UserAPITokenCreate, UserCreate


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
async def test_external_auth_links_existing_user_by_email(monkeypatch) -> None:
    user = User(
        email="admin@example.com",
        first_name="Admin",
        last_name="User",
        is_active=True,
    )
    user.id = uuid4()

    async def missing_identity(*args, **kwargs):
        return None

    async def existing_user(*args, **kwargs):
        return user

    monkeypatch.setattr(service.repository, "get_external_identity", missing_identity)
    monkeypatch.setattr(service.repository, "get_user_by_email", existing_user)
    session = FakeSession()

    response = await service.get_or_create_external_user(
        session,
        ExternalIdentityClaims(
            provider="clerk",
            subject="user_123",
            email="ADMIN@EXAMPLE.COM",
        ),
    )

    identities = [item for item in session.added if isinstance(item, UserExternalIdentity)]
    assert response is user
    assert identities[0].provider == "clerk"
    assert identities[0].subject == "user_123"
    assert identities[0].email == "admin@example.com"


@pytest.mark.asyncio
async def test_external_auth_creates_user_without_local_credentials(monkeypatch) -> None:
    async def missing_identity(*args, **kwargs):
        return None

    async def missing_user(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_external_identity", missing_identity)
    monkeypatch.setattr(service.repository, "get_user_by_email", missing_user)
    session = FakeSession()

    user = await service.get_or_create_external_user(
        session,
        ExternalIdentityClaims(
            provider="clerk",
            subject="user_123",
            email="member@example.com",
            first_name="Member",
            last_name="User",
        ),
    )

    assert user.email == "member@example.com"
    assert user.local_credentials is None
    assert user.is_superuser is False


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


@pytest.mark.asyncio
async def test_update_user_admin_flags_sets_global_roles(monkeypatch) -> None:
    actor = User(email="admin@example.com", is_superuser=True)
    actor.id = uuid4()
    target = User(email="reviewer@example.com")
    target.id = uuid4()

    async def get_user(*args, **kwargs):
        return target

    monkeypatch.setattr(service.repository, "get_user_by_id", get_user)

    user = await service.update_user_admin_flags(
        FakeSession(),
        actor,
        target.id,
        UserAdminUpdate(isGlobalModerator=True, isGlobalPartnerManager=True),
    )

    assert user.is_global_moderator is True
    assert user.is_global_partner_manager is True


@pytest.mark.asyncio
async def test_update_user_admin_flags_rejects_self_superuser_removal(monkeypatch) -> None:
    actor = User(email="admin@example.com", is_superuser=True)
    actor.id = uuid4()

    async def get_user(*args, **kwargs):
        return actor

    monkeypatch.setattr(service.repository, "get_user_by_id", get_user)

    with pytest.raises(InvalidUserRoleUpdateError):
        await service.update_user_admin_flags(
            FakeSession(),
            actor,
            actor.id,
            UserAdminUpdate(isSuperuser=False),
        )


@pytest.mark.asyncio
async def test_create_user_api_token_defaults_to_submission_scopes(monkeypatch) -> None:
    user = User(email="admin@example.com")
    user.id = uuid4()

    async def get_user(*args, **kwargs):
        return user

    monkeypatch.setattr(service.repository, "get_user_by_id", get_user)

    record, token = await service.create_user_api_token(
        FakeSession(),
        user.id,
        UserAPITokenCreate(name="Automation"),
    )

    assert token.startswith("wardn_hub_")
    assert record.scopes == ["catalog:read", "submissions:read", "submissions:write"]


@pytest.mark.asyncio
async def test_create_user_api_token_deduplicates_custom_scopes(monkeypatch) -> None:
    user = User(email="admin@example.com")
    user.id = uuid4()

    async def get_user(*args, **kwargs):
        return user

    monkeypatch.setattr(service.repository, "get_user_by_id", get_user)

    record, _token = await service.create_user_api_token(
        FakeSession(),
        user.id,
        UserAPITokenCreate(
            name="Catalog",
            scopes=["catalog:read", "catalog:read", "submissions:read"],
        ),
    )

    assert record.scopes == ["catalog:read", "submissions:read"]
