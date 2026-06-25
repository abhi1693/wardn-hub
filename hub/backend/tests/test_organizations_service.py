from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.organizations import service
from app.modules.organizations.exceptions import (
    DuplicateOrganizationError,
    OrganizationAccessDeniedError,
)
from app.modules.organizations.models import Organization, OrganizationMembership
from app.modules.organizations.schemas import OrganizationCreate
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
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

    async def refresh(self, instance) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = uuid4()


def superuser() -> User:
    return User(
        id=uuid4(),
        email="admin@example.com",
        first_name="Admin",
        last_name="User",
        is_active=True,
        is_superuser=True,
        is_global_moderator=False,
        is_global_partner_manager=False,
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
        updated_at=datetime(2026, 6, 23, tzinfo=UTC),
    )


def regular_user() -> User:
    user = superuser()
    user.is_superuser = False
    return user


def partner_manager() -> User:
    user = regular_user()
    user.is_global_partner_manager = True
    return user


def organization(*, is_partner: bool) -> Organization:
    return Organization(
        id=uuid4(),
        name="Acme",
        slug="acme",
        status="active",
        is_partner=is_partner,
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
        updated_at=datetime(2026, 6, 23, tzinfo=UTC),
    )


def org_payload() -> OrganizationCreate:
    return OrganizationCreate(name="Acme", slug="acme")


@pytest.mark.asyncio
async def test_create_organization_seeds_roles_and_owner_membership(monkeypatch) -> None:
    async def missing_org(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_organization_by_slug", missing_org)
    session = FakeSession()

    response = await service.create_organization(session, superuser(), org_payload())

    roles = [item for item in session.added if hasattr(item, "permissions")]
    memberships = [item for item in session.added if isinstance(item, OrganizationMembership)]
    assert response.slug == "acme"
    assert len(roles) == 5
    assert len(memberships) == 1
    assert response.current_user_role == "owner"


@pytest.mark.asyncio
async def test_create_organization_requires_superuser() -> None:
    with pytest.raises(OrganizationAccessDeniedError):
        await service.create_organization(FakeSession(), regular_user(), org_payload())


@pytest.mark.asyncio
async def test_create_organization_allows_global_partner_manager(monkeypatch) -> None:
    async def missing_org(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_organization_by_slug", missing_org)

    response = await service.create_organization(FakeSession(), partner_manager(), org_payload())

    assert response.slug == "acme"
    assert response.current_user_role == "owner"


@pytest.mark.asyncio
async def test_create_organization_rejects_duplicate_slug(monkeypatch) -> None:
    async def existing_org(*args, **kwargs):
        return object()

    monkeypatch.setattr(service.repository, "get_organization_by_slug", existing_org)

    with pytest.raises(DuplicateOrganizationError):
        await service.create_organization(FakeSession(), superuser(), org_payload())


@pytest.mark.asyncio
async def test_global_partner_manager_can_manage_partner_memberships(monkeypatch) -> None:
    org = organization(is_partner=True)

    async def get_org(*args, **kwargs):
        return org

    async def get_membership(*args, **kwargs):
        return None

    async def list_memberships(*args, **kwargs):
        return []

    monkeypatch.setattr(service.repository, "get_organization_by_id", get_org)
    monkeypatch.setattr(service.repository, "get_organization_membership", get_membership)
    monkeypatch.setattr(service.repository, "list_organization_memberships", list_memberships)

    response = await service.list_memberships(FakeSession(), partner_manager(), org.id)

    assert response.memberships == []


@pytest.mark.asyncio
async def test_global_partner_manager_cannot_manage_non_partner_memberships(monkeypatch) -> None:
    org = organization(is_partner=False)

    async def get_org(*args, **kwargs):
        return org

    async def get_membership(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_organization_by_id", get_org)
    monkeypatch.setattr(service.repository, "get_organization_membership", get_membership)

    with pytest.raises(OrganizationAccessDeniedError):
        await service.list_memberships(FakeSession(), partner_manager(), org.id)
