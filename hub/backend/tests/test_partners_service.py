from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.organizations.models import Organization
from app.modules.partners import service
from app.modules.partners.exceptions import (
    DuplicatePartnerSupportError,
    InvalidPartnerSupportError,
)
from app.modules.partners.schemas import (
    PartnerOrganizationUpdate,
    PartnerServerSupportCreate,
)
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = False
        self.refreshed: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushed = True

    async def refresh(self, instance: object) -> None:
        now = datetime(2026, 6, 23, tzinfo=UTC)
        if getattr(instance, "id", None) is None:
            instance.id = uuid4()
        if getattr(instance, "created_at", None) is None:
            instance.created_at = now
        if getattr(instance, "updated_at", None) is None:
            instance.updated_at = now
        self.refreshed.append(instance)


def current_user() -> User:
    return User(
        id=uuid4(),
        email="admin@example.com",
        first_name="Admin",
        last_name="User",
        is_active=True,
        is_superuser=True,
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
        updated_at=datetime(2026, 6, 23, tzinfo=UTC),
    )


def organization(*, is_partner: bool = False) -> Organization:
    return Organization(
        id=uuid4(),
        name="Acme",
        slug="acme",
        status="active",
        is_partner=is_partner,
        partner_status="active" if is_partner else "none",
        partner_tier="verified" if is_partner else "community",
        website_url="",
        support_email="",
        partner_profile={},
        partner_internal_notes="",
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
        updated_at=datetime(2026, 6, 23, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_update_partner_organization_sets_metadata_and_audit(monkeypatch) -> None:
    org = organization()

    async def get_org(*args, **kwargs):
        return org

    monkeypatch.setattr(service.organizations_repository, "get_organization_by_id", get_org)
    session = FakeSession()

    response = await service.update_partner_organization(
        session,
        current_user(),
        org.id,
        PartnerOrganizationUpdate(
            isPartner=True,
            partnerStatus="active",
            partnerTier="official",
            websiteUrl="https://example.com",
            supportEmail="support@example.com",
            partnerProfile={"summary": "Official support"},
            partnerInternalNotes="contract signed",
        ),
    )

    audit_events = [item for item in session.added if item.__class__.__name__ == "AuditEvent"]
    assert response.is_partner is True
    assert response.partner_tier == "official"
    assert response.partner_profile == {"summary": "Official support"}
    assert org.partner_internal_notes == "contract signed"
    assert audit_events[0].event_type == "partner.updated"


@pytest.mark.asyncio
async def test_create_server_support_requires_partner_organization(monkeypatch) -> None:
    org = organization(is_partner=False)

    async def get_org(*args, **kwargs):
        return org

    monkeypatch.setattr(service.organizations_repository, "get_organization_by_id", get_org)

    with pytest.raises(InvalidPartnerSupportError):
        await service.create_server_support(
            FakeSession(),
            current_user(),
            org.id,
            PartnerServerSupportCreate(serverName="io.github.example/weather"),
        )


@pytest.mark.asyncio
async def test_create_server_support_rejects_duplicate(monkeypatch) -> None:
    org = organization(is_partner=True)

    async def get_org(*args, **kwargs):
        return org

    async def existing_support(*args, **kwargs):
        return object()

    monkeypatch.setattr(service.organizations_repository, "get_organization_by_id", get_org)
    monkeypatch.setattr(
        service.repository,
        "get_support_by_organization_and_server",
        existing_support,
    )

    with pytest.raises(DuplicatePartnerSupportError):
        await service.create_server_support(
            FakeSession(),
            current_user(),
            org.id,
            PartnerServerSupportCreate(serverName="io.github.example/weather"),
        )
