import socket
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.events import security, service
from app.modules.events.actions import WebhookActionHandler
from app.modules.events.exceptions import EventValidationError
from app.modules.events.models import EventDelivery, EventRecord, EventRule
from app.modules.events.schemas import EventRuleCreate
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.flushed = False
        self.refreshed: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def delete(self, instance: object) -> None:
        self.deleted.append(instance)

    async def flush(self) -> None:
        self.flushed = True
        now = datetime(2026, 6, 27, tzinfo=UTC)
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()
            if getattr(instance, "created_at", None) is None:
                instance.created_at = now
            if getattr(instance, "updated_at", None) is None:
                instance.updated_at = now

    async def refresh(self, instance: object) -> None:
        now = datetime(2026, 6, 27, tzinfo=UTC)
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
    )


def event_record(*, owner_user_id) -> EventRecord:
    event_id = uuid4()
    return EventRecord(
        id=event_id,
        event_type="submission.submitted",
        subject_type="server_submission",
        subject_id=str(uuid4()),
        actor_user_id=owner_user_id,
        owner_user_id=owner_user_id,
        visibility_scope="owner",
        payload={
            "eventId": str(event_id),
            "eventType": "submission.submitted",
            "submission": {
                "id": str(uuid4()),
                "name": "io.github.example/weather",
                "version": "1.0.0",
                "status": "submitted",
                "submissionType": "new_server",
            },
        },
        created_at=datetime(2026, 6, 27, tzinfo=UTC),
    )


def test_delivery_response_includes_event_summary() -> None:
    owner_user_id = uuid4()
    event = event_record(owner_user_id=owner_user_id)
    delivery = EventDelivery(
        id=uuid4(),
        event_record_id=event.id,
        event_rule_id=uuid4(),
        destination_type="webhook",
        destination_url_redacted="https://hooks.example.test/review",
        status="succeeded",
        attempt_count=1,
        request_headers={},
        response_body="ok",
        error_message="",
        created_at=datetime(2026, 6, 27, tzinfo=UTC),
        updated_at=datetime(2026, 6, 27, tzinfo=UTC),
    )

    response = service.delivery_response(delivery, event=event)

    assert response.event is not None
    assert response.event.event_type == "submission.submitted"
    assert response.event.subject_label == "io.github.example/weather"
    assert response.event.subject_version == "1.0.0"


@pytest.mark.asyncio
async def test_create_rule_does_not_generate_signing_secret_by_default() -> None:
    user = current_user()
    session = FakeSession()

    response = await service.create_rule(
        session,
        user,
        EventRuleCreate(
            name="Submission review",
            eventTypes=["submission.submitted"],
            actionConfig={"url": "https://hooks.example.test/review?token=secret"},
        ),
    )

    rule = next(item for item in session.added if isinstance(item, EventRule))
    assert response.signing_secret is None
    assert "signingSecret" not in rule.action_config
    assert "signingSecretDigest" not in rule.action_config
    assert response.action_config == {
        "url": "https://hooks.example.test/review",
        "hasSigningSecret": False,
    }
    delivery = next(item for item in session.added if isinstance(item, EventDelivery))
    event = next(item for item in session.added if isinstance(item, EventRecord))
    assert delivery.status == "pending"
    assert delivery.event_rule_id == rule.id
    assert delivery.event_record_id == event.id
    assert event.processed_at is not None
    assert event.payload["ping"] is True
    assert event.payload["subject"]["eventTypes"] == ["submission.submitted"]


@pytest.mark.asyncio
async def test_create_rule_generates_signing_secret_when_requested() -> None:
    user = current_user()
    session = FakeSession()

    response = await service.create_rule(
        session,
        user,
        EventRuleCreate(
            name="Submission review",
            eventTypes=["submission.submitted"],
            actionConfig={
                "url": "https://hooks.example.test/review",
                "generateSigningSecret": True,
            },
        ),
    )

    rule = next(item for item in session.added if isinstance(item, EventRule))
    assert response.signing_secret
    assert rule.action_config["signingSecret"] == response.signing_secret
    assert rule.action_config["signingSecretDigest"] == security.signing_secret_digest(
        response.signing_secret
    )
    assert response.action_config == {
        "url": "https://hooks.example.test/review",
        "signingSecretDigest": rule.action_config["signingSecretDigest"],
        "hasSigningSecret": True,
    }
    assert any(isinstance(item, EventDelivery) for item in session.added)


@pytest.mark.asyncio
async def test_create_rule_rejects_private_webhook_url_for_normal_user() -> None:
    with pytest.raises(EventValidationError, match="private webhook"):
        await service.create_rule(
            FakeSession(),
            current_user(),
            EventRuleCreate(
                name="Bad destination",
                eventTypes=["submission.submitted"],
                actionConfig={"url": "http://127.0.0.1:9000/hook"},
            ),
        )


@pytest.mark.asyncio
async def test_create_rule_rejects_webhook_hostname_resolving_private_for_normal_user(
    monkeypatch,
) -> None:
    def private_dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]

    monkeypatch.setattr(security.socket, "getaddrinfo", private_dns)

    with pytest.raises(EventValidationError, match="private webhook"):
        await service.create_rule(
            FakeSession(),
            current_user(),
            EventRuleCreate(
                name="Bad destination",
                eventTypes=["submission.submitted"],
                actionConfig={"url": "https://hooks.example.test/review"},
            ),
        )


@pytest.mark.asyncio
async def test_create_rule_allows_private_resolved_hostname_for_superuser(monkeypatch) -> None:
    def private_dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]

    monkeypatch.setattr(security.socket, "getaddrinfo", private_dns)
    session = FakeSession()

    await service.create_rule(
        session,
        current_user(is_superuser=True),
        EventRuleCreate(
            name="Private destination",
            eventTypes=["submission.submitted"],
            actionConfig={"url": "https://hooks.example.test/review"},
        ),
    )

    rule = next(item for item in session.added if isinstance(item, EventRule))
    assert rule.action_config["allowPrivateDestinations"] is True


@pytest.mark.asyncio
async def test_delivery_revalidates_webhook_hostname_before_sending(monkeypatch) -> None:
    def private_dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]

    monkeypatch.setattr(security.socket, "getaddrinfo", private_dns)
    owner_user_id = uuid4()
    event = event_record(owner_user_id=owner_user_id)
    rule = EventRule(
        id=uuid4(),
        owner_user_id=owner_user_id,
        name="Review",
        description="",
        is_enabled=True,
        event_types=["submission.submitted"],
        conditions={},
        action_type="webhook",
        action_config={"url": "https://hooks.example.test/review"},
        failure_policy={},
        created_at=datetime(2026, 6, 27, tzinfo=UTC),
        updated_at=datetime(2026, 6, 27, tzinfo=UTC),
    )
    delivery = EventDelivery(
        id=uuid4(),
        event_record_id=event.id,
        event_rule_id=rule.id,
        destination_type="webhook",
        destination_url_redacted="https://hooks.example.test/review",
        status="pending",
        attempt_count=1,
        request_headers={},
        created_at=datetime(2026, 6, 27, tzinfo=UTC),
        updated_at=datetime(2026, 6, 27, tzinfo=UTC),
    )

    result = await WebhookActionHandler().deliver(event=event, rule=rule, delivery=delivery)

    assert result.status == "failed"
    assert result.error_message == "private webhook destinations are not allowed"


def test_webhook_signature_round_trips() -> None:
    raw_body = b'{"eventType":"submission.submitted"}'
    signature = security.sign_webhook_payload(raw_body, "shared-secret", timestamp=1234)

    assert security.verify_webhook_signature(
        raw_body,
        "shared-secret",
        signature,
        now=1234,
    )
    assert not security.verify_webhook_signature(raw_body, "wrong-secret", signature, now=1234)


@pytest.mark.asyncio
async def test_create_deliveries_for_event_matches_visible_rule(monkeypatch) -> None:
    owner_user_id = uuid4()
    event = event_record(owner_user_id=owner_user_id)
    rule = EventRule(
        id=uuid4(),
        owner_user_id=owner_user_id,
        name="Review",
        description="",
        is_enabled=True,
        event_types=["submission.submitted"],
        conditions={"submissionTypes": ["new_server"], "serverNamePrefix": "io.github."},
        action_type="webhook",
        action_config={"url": "https://hooks.example.test/review", "signingSecret": "secret"},
        failure_policy={},
        created_at=datetime(2026, 6, 27, tzinfo=UTC),
        updated_at=datetime(2026, 6, 27, tzinfo=UTC),
    )

    async def list_rules(*args, **kwargs):
        return [rule]

    monkeypatch.setattr(service.repository, "list_enabled_rules_for_event_type", list_rules)
    session = FakeSession()

    deliveries = await service.create_deliveries_for_event(session, event)

    assert len(deliveries) == 1
    assert deliveries[0].status == "pending"
    assert deliveries[0].destination_url_redacted == "https://hooks.example.test/review"
    assert event.processed_at is not None
    assert rule.last_triggered_at is not None


@pytest.mark.asyncio
async def test_internal_registry_automation_rule_can_receive_registry_events(monkeypatch) -> None:
    owner_user_id = uuid4()
    event = EventRecord(
        id=uuid4(),
        event_type="registry.version.published",
        subject_type="registry_server_version",
        subject_id=str(uuid4()),
        actor_user_id=owner_user_id,
        owner_user_id=owner_user_id,
        visibility_scope="owner",
        payload={
            "eventId": str(uuid4()),
            "eventType": "registry.version.published",
            "subject": {
                "type": "registry_server_version",
                "id": str(uuid4()),
                "name": "io.github.example/weather",
                "version": "1.0.0",
            },
            "registryVersion": {
                "id": str(uuid4()),
                "name": "io.github.example/weather",
                "version": "1.0.0",
            },
        },
        created_at=datetime(2026, 6, 27, tzinfo=UTC),
    )
    unrelated_owner_rule = EventRule(
        id=uuid4(),
        owner_user_id=uuid4(),
        name="Other owner",
        description="",
        is_enabled=True,
        event_types=["registry.version.published"],
        conditions={},
        action_type="webhook",
        action_config={"url": "https://hooks.example.test/review"},
        failure_policy={},
        created_at=datetime(2026, 6, 27, tzinfo=UTC),
        updated_at=datetime(2026, 6, 27, tzinfo=UTC),
    )
    internal_rule = EventRule(
        id=uuid4(),
        owner_user_id=None,
        owner_organization_id=None,
        name="Wardn Hub Scoring",
        description="Internal scorer webhook",
        is_enabled=True,
        event_types=["registry.version.published"],
        conditions={},
        action_type="webhook",
        action_config={
            "url": "http://wardn-hub-scoring.wardn.svc.cluster.local:8080/webhooks/wardn/server-version",
            "internalAutomation": True,
            "allowPrivateDestinations": True,
        },
        failure_policy={},
        created_at=datetime(2026, 6, 27, tzinfo=UTC),
        updated_at=datetime(2026, 6, 27, tzinfo=UTC),
    )

    async def list_rules(*args, **kwargs):
        return [unrelated_owner_rule, internal_rule]

    monkeypatch.setattr(service.repository, "list_enabled_rules_for_event_type", list_rules)
    session = FakeSession()

    deliveries = await service.create_deliveries_for_event(session, event)

    assert len(deliveries) == 1
    assert deliveries[0].event_rule_id == internal_rule.id
    assert internal_rule.last_triggered_at is not None
    assert unrelated_owner_rule.last_triggered_at is None
