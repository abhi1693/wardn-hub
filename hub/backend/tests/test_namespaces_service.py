from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.namespaces import service
from app.modules.namespaces.exceptions import (
    DuplicateNamespaceClaimError,
    InvalidNamespaceClaimTransitionError,
)
from app.modules.namespaces.models import NamespaceClaim
from app.modules.namespaces.schemas import NamespaceClaimCreate
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


def current_user(*, is_superuser: bool = False) -> User:
    return User(
        id=uuid4(),
        email=f"{uuid4()}@example.com",
        first_name="Test",
        last_name="User",
        is_active=True,
        is_superuser=is_superuser,
        is_global_moderator=False,
        is_global_partner_manager=False,
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
        updated_at=datetime(2026, 6, 23, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_create_namespace_claim_normalizes_and_emits_audit(monkeypatch) -> None:
    async def missing_claim(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_active_claim_by_namespace", missing_claim)
    session = FakeSession()

    response = await service.create_namespace_claim(
        session,
        current_user(),
        NamespaceClaimCreate(namespace="Io.GitHub.Example"),
    )

    audit_events = [item for item in session.added if item.__class__.__name__ == "AuditEvent"]
    assert response.namespace == "io.github.example/*"
    assert response.status == "pending"
    assert len(audit_events) == 1
    assert audit_events[0].event_type == "namespace.claimed"


@pytest.mark.asyncio
async def test_create_namespace_claim_rejects_duplicate_active_claim(monkeypatch) -> None:
    async def existing_claim(*args, **kwargs):
        return object()

    monkeypatch.setattr(service.repository, "get_active_claim_by_namespace", existing_claim)

    with pytest.raises(DuplicateNamespaceClaimError):
        await service.create_namespace_claim(
            FakeSession(),
            current_user(),
            NamespaceClaimCreate(namespace="com.example/*", method="dns"),
        )


def test_namespace_claim_schema_rejects_invalid_namespace() -> None:
    with pytest.raises(ValidationError):
        NamespaceClaimCreate(namespace="not a namespace")


@pytest.mark.asyncio
async def test_verify_namespace_claim_requires_pending_or_failed(monkeypatch) -> None:
    claim = NamespaceClaim(
        id=uuid4(),
        namespace="com.example/*",
        owner_organization_id=None,
        claimed_by_user_id=uuid4(),
        method="dns",
        status="revoked",
        verification_payload={},
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
        updated_at=datetime(2026, 6, 23, tzinfo=UTC),
    )

    async def get_claim(*args, **kwargs):
        return claim

    monkeypatch.setattr(service.repository, "get_claim_by_id", get_claim)

    with pytest.raises(InvalidNamespaceClaimTransitionError):
        await service.verify_namespace_claim(
            FakeSession(),
            current_user(is_superuser=True),
            claim.id,
            service.NamespaceClaimDecision(),
        )
