import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import emit_audit_event
from app.modules.events import repository, security
from app.modules.events.actions import HANDLERS
from app.modules.events.exceptions import (
    EventAccessDeniedError,
    EventDeliveryError,
    EventDeliveryNotFoundError,
    EventRuleNotFoundError,
    EventValidationError,
)
from app.modules.events.models import EventDelivery, EventRecord, EventRule
from app.modules.events.schemas import (
    EventDeliveryEventSummary,
    EventDeliveryListResponse,
    EventDeliveryRead,
    EventRecordRead,
    EventRuleCreate,
    EventRuleListResponse,
    EventRuleRead,
    EventRuleUpdate,
    EventSecretRotateResponse,
    EventTypeListResponse,
    EventTypeRead,
)
from app.modules.events.types import EVENT_TYPES, is_supported_event_type
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
)
from app.modules.organizations.service import (
    require_organization_member,
    require_organization_permission,
)
from app.modules.users.models import User, UserAPIToken


def event_type_response() -> EventTypeListResponse:
    return EventTypeListResponse(
        eventTypes=[
            EventTypeRead(
                eventType=definition.event_type,
                label=definition.label,
                description=definition.description,
                subjectType=definition.subject_type,
            )
            for definition in EVENT_TYPES
        ]
    )


def redact_action_config(action_type: str, config: dict[str, Any]) -> dict[str, Any]:
    if action_type != "webhook":
        return dict(config)
    redacted = dict(config)
    redacted.pop("signingSecret", None)
    redacted.pop("generateSigningSecret", None)
    if "url" in redacted:
        redacted["url"] = security.redacted_url(str(redacted["url"]))
    redacted["hasSigningSecret"] = bool(config.get("signingSecret"))
    return redacted


def rule_response(rule: EventRule, *, signing_secret: str | None = None) -> EventRuleRead:
    return EventRuleRead(
        id=rule.id,
        ownerUserId=rule.owner_user_id,
        ownerOrganizationId=rule.owner_organization_id,
        createdByUserId=rule.created_by_user_id,
        name=rule.name,
        description=rule.description,
        isEnabled=rule.is_enabled,
        eventTypes=rule.event_types,
        conditions=rule.conditions,
        actionType=rule.action_type,
        actionConfig=redact_action_config(rule.action_type, rule.action_config),
        failurePolicy=rule.failure_policy,
        lastTriggeredAt=rule.last_triggered_at,
        signingSecret=signing_secret,
        createdAt=rule.created_at,
        updatedAt=rule.updated_at,
    )


def delivery_event_summary(event: EventRecord | None) -> EventDeliveryEventSummary | None:
    if event is None:
        return None
    payload = event.payload if isinstance(event.payload, dict) else {}
    subject = payload.get("subject") if isinstance(payload.get("subject"), dict) else {}
    submission = payload.get("submission") if isinstance(payload.get("submission"), dict) else {}
    registry_version = (
        payload.get("registryVersion") if isinstance(payload.get("registryVersion"), dict) else {}
    )
    registry_server = (
        payload.get("registryServer") if isinstance(payload.get("registryServer"), dict) else {}
    )
    subject_label = str(
        submission.get("name")
        or registry_version.get("name")
        or registry_server.get("name")
        or subject.get("name")
        or event.subject_id
    )
    subject_version = str(
        submission.get("version")
        or registry_version.get("version")
        or subject.get("version")
        or ""
    )
    occurred_at = str(payload.get("occurredAt") or "")
    return EventDeliveryEventSummary(
        id=event.id,
        eventType=event.event_type,
        subjectType=event.subject_type,
        subjectId=event.subject_id,
        subjectLabel=subject_label,
        subjectVersion=subject_version,
        occurredAt=occurred_at,
    )


def delivery_response(
    delivery: EventDelivery,
    *,
    event: EventRecord | None = None,
) -> EventDeliveryRead:
    return EventDeliveryRead(
        id=delivery.id,
        eventRecordId=delivery.event_record_id,
        event=delivery_event_summary(event),
        eventRuleId=delivery.event_rule_id,
        destinationType=delivery.destination_type,
        destinationUrlRedacted=delivery.destination_url_redacted,
        status=delivery.status,
        attemptCount=delivery.attempt_count,
        nextAttemptAt=delivery.next_attempt_at,
        lastAttemptAt=delivery.last_attempt_at,
        responseStatus=delivery.response_status,
        responseBody=delivery.response_body,
        errorMessage=delivery.error_message,
        requestHeaders=delivery.request_headers,
        createdAt=delivery.created_at,
        updatedAt=delivery.updated_at,
    )


def event_record_response(event: EventRecord) -> EventRecordRead:
    return EventRecordRead(
        id=event.id,
        eventType=event.event_type,
        subjectType=event.subject_type,
        subjectId=event.subject_id,
        actorUserId=event.actor_user_id,
        actorTokenId=event.actor_token_id,
        ownerUserId=event.owner_user_id,
        ownerOrganizationId=event.owner_organization_id,
        visibilityScope=event.visibility_scope,
        payload=event.payload,
        processedAt=event.processed_at,
        createdAt=event.created_at,
    )


def validate_event_types(event_types: list[str]) -> None:
    unsupported = [
        event_type for event_type in event_types if not is_supported_event_type(event_type)
    ]
    if unsupported:
        raise EventValidationError("unsupported event type: " + ", ".join(unsupported))


def validate_webhook_action(action_config: dict[str, Any], *, allow_private: bool) -> str:
    url = str(action_config.get("url") or "").strip()
    if not url:
        raise EventValidationError("webhook actionConfig.url is required")
    return url


def normalize_action_config(
    action_type: str,
    action_config: dict[str, Any],
    *,
    allow_private: bool,
) -> tuple[dict[str, Any], str | None]:
    if action_type != "webhook":
        raise EventValidationError("unsupported action type")
    url = validate_webhook_action(action_config, allow_private=allow_private)
    uses_private_destination = security.validate_webhook_url(url, allow_private=allow_private)
    normalized = dict(action_config)
    normalized["url"] = url
    if uses_private_destination:
        normalized["allowPrivateDestinations"] = True
    else:
        normalized.pop("allowPrivateDestinations", None)
    should_generate_secret = normalized.get("generateSigningSecret") is True
    normalized.pop("generateSigningSecret", None)
    signing_secret = str(normalized.get("signingSecret") or "").strip()
    generated_secret = None
    if not signing_secret and should_generate_secret:
        signing_secret = security.generate_signing_secret()
        generated_secret = signing_secret
    if signing_secret:
        normalized["signingSecret"] = signing_secret
        normalized["signingSecretDigest"] = security.signing_secret_digest(signing_secret)
    else:
        normalized.pop("signingSecret", None)
        normalized.pop("signingSecretDigest", None)
    return normalized, generated_secret


async def resolve_rule_owner(
    session: AsyncSession,
    user: User,
    *,
    owner_user_id: uuid.UUID | None,
    owner_organization_id: uuid.UUID | None,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    if owner_user_id is None and owner_organization_id is None:
        owner_user_id = user.id
    if owner_user_id is not None and not user.is_superuser and owner_user_id != user.id:
        raise EventAccessDeniedError("event rule owner user access denied")
    if owner_organization_id is not None:
        try:
            await require_organization_permission(
                session,
                user,
                owner_organization_id,
                "organization.manage",
            )
        except OrganizationNotFoundError as exc:
            raise EventValidationError("owner organization not found") from exc
        except OrganizationAccessDeniedError as exc:
            raise EventAccessDeniedError("owner organization access denied") from exc
    return owner_user_id, owner_organization_id


async def ensure_can_manage_rule(session: AsyncSession, user: User, rule: EventRule) -> None:
    if user.is_superuser:
        return
    if rule.owner_user_id == user.id:
        return
    if rule.owner_organization_id is not None:
        try:
            await require_organization_permission(
                session,
                user,
                rule.owner_organization_id,
                "organization.manage",
            )
        except (OrganizationNotFoundError, OrganizationAccessDeniedError) as exc:
            raise EventAccessDeniedError("event rule access denied") from exc
        return
    raise EventAccessDeniedError("event rule access denied")


async def ensure_can_read_rule(session: AsyncSession, user: User, rule: EventRule) -> None:
    if user.is_superuser:
        return
    if rule.owner_user_id == user.id:
        return
    if rule.owner_organization_id is not None:
        try:
            await require_organization_member(session, user, rule.owner_organization_id)
        except (OrganizationNotFoundError, OrganizationAccessDeniedError) as exc:
            raise EventAccessDeniedError("event rule access denied") from exc
        return
    raise EventAccessDeniedError("event rule access denied")


async def ensure_can_read_event_record(
    session: AsyncSession,
    user: User,
    event: EventRecord,
) -> None:
    if user.is_superuser:
        return
    if event.owner_user_id == user.id:
        return
    if event.owner_organization_id is not None:
        try:
            await require_organization_member(session, user, event.owner_organization_id)
        except (OrganizationNotFoundError, OrganizationAccessDeniedError) as exc:
            raise EventAccessDeniedError("event delivery access denied") from exc
        return
    raise EventAccessDeniedError("event delivery access denied")


def api_token_organization_ids(api_token: UserAPIToken | None) -> set[str]:
    if api_token is None:
        return set()
    return {str(organization_id) for organization_id in api_token.organization_ids}


def ensure_api_token_rule_access(api_token: UserAPIToken | None, rule: EventRule) -> None:
    allowed = api_token_organization_ids(api_token)
    if not allowed:
        return
    if rule.owner_organization_id is None or str(rule.owner_organization_id) not in allowed:
        raise EventAccessDeniedError("API token organization access denied")


async def list_event_types() -> EventTypeListResponse:
    return event_type_response()


async def list_rules(
    session: AsyncSession,
    user: User,
    *,
    api_token: UserAPIToken | None = None,
) -> EventRuleListResponse:
    rules = await repository.list_event_rules(
        session,
        user_id=user.id,
        include_all=user.is_superuser,
    )
    allowed = api_token_organization_ids(api_token)
    if allowed:
        rules = [
            rule
            for rule in rules
            if rule.owner_organization_id is not None and str(rule.owner_organization_id) in allowed
        ]
    return EventRuleListResponse(rules=[rule_response(rule) for rule in rules])


async def create_rule(
    session: AsyncSession,
    user: User,
    payload: EventRuleCreate,
    *,
    api_token: UserAPIToken | None = None,
) -> EventRuleRead:
    validate_event_types(payload.event_types)
    owner_user_id, owner_organization_id = await resolve_rule_owner(
        session,
        user,
        owner_user_id=payload.owner_user_id,
        owner_organization_id=payload.owner_organization_id,
    )
    action_config, generated_secret = normalize_action_config(
        payload.action_type,
        payload.action_config,
        allow_private=user.is_superuser,
    )
    rule = EventRule(
        owner_user_id=owner_user_id,
        owner_organization_id=owner_organization_id,
        created_by_user_id=user.id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        is_enabled=payload.is_enabled,
        event_types=payload.event_types,
        conditions=payload.conditions,
        action_type=payload.action_type,
        action_config=action_config,
        failure_policy=payload.failure_policy,
    )
    ensure_api_token_rule_access(api_token, rule)
    session.add(rule)
    await session.flush()
    await session.refresh(rule)
    await create_rule_ping_delivery(
        session,
        rule,
        actor_user_id=user.id,
        actor_token_id=api_token.id if api_token is not None and api_token.id else None,
        kind="ping",
    )
    return rule_response(rule, signing_secret=generated_secret)


async def get_rule(
    session: AsyncSession,
    user: User,
    rule_id: uuid.UUID,
    *,
    api_token: UserAPIToken | None = None,
) -> EventRuleRead:
    rule = await repository.get_event_rule_by_id(session, rule_id)
    if rule is None:
        raise EventRuleNotFoundError("event rule not found")
    await ensure_can_read_rule(session, user, rule)
    ensure_api_token_rule_access(api_token, rule)
    return rule_response(rule)


async def update_rule(
    session: AsyncSession,
    user: User,
    rule_id: uuid.UUID,
    payload: EventRuleUpdate,
    *,
    api_token: UserAPIToken | None = None,
) -> EventRuleRead:
    rule = await repository.get_event_rule_by_id(session, rule_id)
    if rule is None:
        raise EventRuleNotFoundError("event rule not found")
    await ensure_can_manage_rule(session, user, rule)
    ensure_api_token_rule_access(api_token, rule)

    next_owner_user_id = (
        payload.owner_user_id if "owner_user_id" in payload.model_fields_set else rule.owner_user_id
    )
    next_owner_organization_id = (
        payload.owner_organization_id
        if "owner_organization_id" in payload.model_fields_set
        else rule.owner_organization_id
    )
    next_owner_user_id, next_owner_organization_id = await resolve_rule_owner(
        session,
        user,
        owner_user_id=next_owner_user_id,
        owner_organization_id=next_owner_organization_id,
    )
    rule.owner_user_id = next_owner_user_id
    rule.owner_organization_id = next_owner_organization_id

    if payload.name is not None:
        rule.name = payload.name.strip()
    if payload.description is not None:
        rule.description = payload.description.strip()
    if payload.is_enabled is not None:
        rule.is_enabled = payload.is_enabled
    if payload.event_types is not None:
        validate_event_types(payload.event_types)
        rule.event_types = payload.event_types
    if payload.conditions is not None:
        rule.conditions = payload.conditions
    if payload.action_type is not None:
        rule.action_type = payload.action_type
    if payload.action_config is not None:
        action_config = dict(payload.action_config)
        if "signingSecret" not in action_config and rule.action_type == "webhook":
            action_config["signingSecret"] = rule.action_config.get("signingSecret")
        rule.action_config, _generated_secret = normalize_action_config(
            rule.action_type,
            action_config,
            allow_private=user.is_superuser,
        )
    if payload.failure_policy is not None:
        rule.failure_policy = payload.failure_policy
    ensure_api_token_rule_access(api_token, rule)
    await session.flush()
    await session.refresh(rule)
    return rule_response(rule)


async def delete_rule(
    session: AsyncSession,
    user: User,
    rule_id: uuid.UUID,
    *,
    api_token: UserAPIToken | None = None,
) -> None:
    rule = await repository.get_event_rule_by_id(session, rule_id)
    if rule is None:
        raise EventRuleNotFoundError("event rule not found")
    await ensure_can_manage_rule(session, user, rule)
    ensure_api_token_rule_access(api_token, rule)
    await repository.delete_event_rule(session, rule)


async def rotate_rule_secret(
    session: AsyncSession,
    user: User,
    rule_id: uuid.UUID,
    *,
    api_token: UserAPIToken | None = None,
) -> EventSecretRotateResponse:
    rule = await repository.get_event_rule_by_id(session, rule_id)
    if rule is None:
        raise EventRuleNotFoundError("event rule not found")
    await ensure_can_manage_rule(session, user, rule)
    ensure_api_token_rule_access(api_token, rule)
    secret = security.generate_signing_secret()
    action_config = dict(rule.action_config)
    action_config["signingSecret"] = secret
    action_config["signingSecretDigest"] = security.signing_secret_digest(secret)
    rule.action_config = action_config
    await session.flush()
    await session.refresh(rule)
    return EventSecretRotateResponse(rule=rule_response(rule), signingSecret=secret)


def subject_payload(
    *,
    event_id: uuid.UUID,
    event_type: str,
    occurred_at: datetime,
    actor_user_id: uuid.UUID | None,
    actor_token_id: uuid.UUID | None,
    subject_type: str,
    subject_id: str | uuid.UUID,
    subject: dict[str, Any] | None = None,
    links: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "eventId": str(event_id),
        "eventType": event_type,
        "schemaVersion": "2026-06-27",
        "occurredAt": occurred_at.isoformat().replace("+00:00", "Z"),
        "actor": {
            "userId": str(actor_user_id) if actor_user_id else None,
            "tokenId": str(actor_token_id) if actor_token_id else None,
        },
        "subject": {"type": subject_type, "id": str(subject_id), **(subject or {})},
        "links": links or {},
    }


async def emit_event_record(
    session: AsyncSession,
    *,
    event_id: uuid.UUID | None = None,
    event_type: str,
    subject_type: str,
    subject_id: str | uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
    actor_token_id: uuid.UUID | None = None,
    owner_user_id: uuid.UUID | None = None,
    owner_organization_id: uuid.UUID | None = None,
    visibility_scope: str = "owner",
    payload: dict[str, Any] | None = None,
) -> EventRecord:
    if not is_supported_event_type(event_type):
        raise EventValidationError("unsupported event type")
    event = EventRecord(
        id=event_id or uuid.uuid4(),
        event_type=event_type,
        subject_type=subject_type,
        subject_id=str(subject_id),
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        owner_user_id=owner_user_id,
        owner_organization_id=owner_organization_id,
        visibility_scope=visibility_scope,
        payload=payload or {},
    )
    session.add(event)
    await session.flush()
    return event


async def emit_audit_and_event(
    session: AsyncSession,
    *,
    event_id: uuid.UUID | None = None,
    event_type: str,
    subject_type: str,
    subject_id: str | uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
    actor_token_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    owner_user_id: uuid.UUID | None = None,
    owner_organization_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    event_payload: dict[str, Any] | None = None,
    visibility_scope: str = "owner",
) -> tuple[object, EventRecord]:
    audit_event = await emit_audit_event(
        session,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        organization_id=organization_id,
        metadata=metadata,
    )
    event_record = await emit_event_record(
        session,
        event_id=event_id,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        owner_user_id=owner_user_id,
        owner_organization_id=owner_organization_id,
        visibility_scope=visibility_scope,
        payload=event_payload,
    )
    return audit_event, event_record


def rule_matches_event(rule: EventRule, event: EventRecord) -> bool:
    if event.event_type not in rule.event_types:
        return False
    conditions = rule.conditions or {}
    submission = event.payload.get("submission") if isinstance(event.payload, dict) else None
    if not isinstance(submission, dict):
        submission = {}
    submission_types = conditions.get("submissionTypes")
    if (
        isinstance(submission_types, list)
        and submission.get("submissionType") not in submission_types
    ):
        return False
    statuses = conditions.get("statuses")
    if isinstance(statuses, list) and submission.get("status") not in statuses:
        return False
    prefix = conditions.get("serverNamePrefix")
    if isinstance(prefix, str) and prefix:
        name = str(submission.get("name") or event.payload.get("subject", {}).get("name") or "")
        if not name.startswith(prefix):
            return False
    owner_organization_ids = conditions.get("ownerOrganizationIds")
    if isinstance(owner_organization_ids, list):
        event_org_id = str(event.owner_organization_id) if event.owner_organization_id else None
        if event_org_id not in {str(item) for item in owner_organization_ids}:
            return False
    return True


def rule_can_see_event(rule: EventRule, event: EventRecord) -> bool:
    if rule.owner_user_id is not None and event.owner_user_id == rule.owner_user_id:
        return True
    if (
        rule.owner_organization_id is not None
        and event.owner_organization_id == rule.owner_organization_id
    ):
        return True
    return False


async def create_deliveries_for_event(
    session: AsyncSession,
    event: EventRecord,
) -> list[EventDelivery]:
    rules = await repository.list_enabled_rules_for_event_type(session, event.event_type)
    deliveries: list[EventDelivery] = []
    for rule in rules:
        if not rule_can_see_event(rule, event) or not rule_matches_event(rule, event):
            continue
        destination_url = str(rule.action_config.get("url") or "")
        delivery = EventDelivery(
            event_record_id=event.id,
            event_rule_id=rule.id,
            destination_type=rule.action_type,
            destination_url_redacted=security.redacted_url(destination_url),
            status="pending",
            attempt_count=0,
            request_headers={},
        )
        rule.last_triggered_at = datetime.now(UTC)
        session.add(delivery)
        deliveries.append(delivery)
    event.processed_at = datetime.now(UTC)
    await session.flush()
    return deliveries


async def create_rule_ping_delivery(
    session: AsyncSession,
    rule: EventRule,
    *,
    actor_user_id: uuid.UUID | None,
    actor_token_id: uuid.UUID | None = None,
    kind: str,
) -> EventDelivery:
    occurred_at = datetime.now(UTC)
    event = await emit_event_record(
        session,
        event_type=rule.event_types[0],
        subject_type="event_rule",
        subject_id=rule.id,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        owner_user_id=rule.owner_user_id,
        owner_organization_id=rule.owner_organization_id,
        visibility_scope="owner",
        payload={
            "eventId": "",
            "eventType": rule.event_types[0],
            "schemaVersion": "2026-06-27",
            "occurredAt": occurred_at.isoformat().replace("+00:00", "Z"),
            "actor": {
                "userId": str(actor_user_id) if actor_user_id else None,
                "tokenId": str(actor_token_id) if actor_token_id else None,
            },
            "subject": {
                "type": "event_rule",
                "id": str(rule.id),
                "name": rule.name,
                "eventTypes": rule.event_types,
            },
            "links": {"eventRuleApiUrl": f"/api/v1/events/rules/{rule.id}"},
            kind: True,
        },
    )
    event.payload = {**event.payload, "eventId": str(event.id)}
    event.processed_at = datetime.now(UTC)
    delivery = EventDelivery(
        event_record_id=event.id,
        event_rule_id=rule.id,
        destination_type=rule.action_type,
        destination_url_redacted=security.redacted_url(str(rule.action_config.get("url") or "")),
        status="pending",
        attempt_count=0,
        request_headers={},
    )
    session.add(delivery)
    await session.flush()
    return delivery


async def process_pending_events(session: AsyncSession, *, limit: int = 50) -> int:
    events = await repository.list_unprocessed_event_records(session, limit=limit)
    count = 0
    for event in events:
        deliveries = await create_deliveries_for_event(session, event)
        count += len(deliveries)
    return count


async def dispatch_due_deliveries(session: AsyncSession, *, limit: int = 50) -> int:
    now = datetime.now(UTC)
    deliveries = await repository.list_due_event_deliveries(session, now=now, limit=limit)
    delivered = 0
    for delivery in deliveries:
        event = await repository.get_event_record_by_id(session, delivery.event_record_id)
        rule = (
            await repository.get_event_rule_by_id(session, delivery.event_rule_id)
            if delivery.event_rule_id is not None
            else None
        )
        if event is None or rule is None or not rule.is_enabled:
            delivery.status = "disabled"
            continue
        handler = HANDLERS.get(rule.action_type)
        if handler is None:
            delivery.status = "failed"
            delivery.error_message = f"unsupported action type: {rule.action_type}"
            continue
        delivery.status = "running"
        delivery.attempt_count += 1
        delivery.last_attempt_at = now
        result = await handler.deliver(event=event, rule=rule, delivery=delivery)
        delivery.status = result.status
        delivery.response_status = result.response_status
        delivery.response_body = result.response_body
        delivery.error_message = result.error_message
        delivery.next_attempt_at = result.next_attempt_at
        delivered += 1
    await session.flush()
    return delivered


async def list_deliveries(
    session: AsyncSession,
    user: User,
    *,
    api_token: UserAPIToken | None = None,
    limit: int = 50,
    rule_id: uuid.UUID | None = None,
) -> EventDeliveryListResponse:
    deliveries = await repository.list_event_deliveries(
        session,
        user_id=user.id,
        include_all=user.is_superuser,
        rule_id=rule_id,
        limit=limit,
    )
    allowed = api_token_organization_ids(api_token)
    if allowed:
        filtered: list[EventDelivery] = []
        for delivery in deliveries:
            if delivery.event_rule_id is None:
                continue
            rule = await repository.get_event_rule_by_id(session, delivery.event_rule_id)
            if rule and rule.owner_organization_id and str(rule.owner_organization_id) in allowed:
                filtered.append(delivery)
        deliveries = filtered
    events_by_id: dict[uuid.UUID, EventRecord] = {}
    for delivery in deliveries:
        event = await repository.get_event_record_by_id(session, delivery.event_record_id)
        if event is not None:
            events_by_id[event.id] = event
    return EventDeliveryListResponse(
        deliveries=[
            delivery_response(item, event=events_by_id.get(item.event_record_id))
            for item in deliveries
        ]
    )


async def get_delivery(
    session: AsyncSession,
    user: User,
    delivery_id: uuid.UUID,
    *,
    api_token: UserAPIToken | None = None,
) -> EventDeliveryRead:
    delivery = await repository.get_event_delivery_by_id(session, delivery_id)
    if delivery is None:
        raise EventDeliveryNotFoundError("event delivery not found")
    rule = (
        await repository.get_event_rule_by_id(session, delivery.event_rule_id)
        if delivery.event_rule_id is not None
        else None
    )
    if rule is not None:
        await ensure_can_read_rule(session, user, rule)
        ensure_api_token_rule_access(api_token, rule)
        event = await repository.get_event_record_by_id(session, delivery.event_record_id)
    else:
        event = await repository.get_event_record_by_id(session, delivery.event_record_id)
        if event is None:
            raise EventAccessDeniedError("event delivery access denied")
        await ensure_can_read_event_record(session, user, event)
    return delivery_response(delivery, event=event)


async def replay_delivery(
    session: AsyncSession,
    user: User,
    delivery_id: uuid.UUID,
    *,
    api_token: UserAPIToken | None = None,
) -> EventDeliveryRead:
    delivery = await repository.get_event_delivery_by_id(session, delivery_id)
    if delivery is None:
        raise EventDeliveryNotFoundError("event delivery not found")
    if delivery.event_rule_id is None:
        raise EventAccessDeniedError("event delivery access denied")
    rule = await repository.get_event_rule_by_id(session, delivery.event_rule_id)
    if rule is None:
        raise EventAccessDeniedError("event delivery access denied")
    await ensure_can_manage_rule(session, user, rule)
    ensure_api_token_rule_access(api_token, rule)
    if delivery.status not in {"failed", "retrying"}:
        raise EventDeliveryError("only failed or retrying deliveries can be replayed")
    delivery.status = "pending"
    delivery.next_attempt_at = None
    delivery.error_message = ""
    await session.flush()
    await session.refresh(delivery)
    event = await repository.get_event_record_by_id(session, delivery.event_record_id)
    return delivery_response(delivery, event=event)


async def test_rule_delivery(
    session: AsyncSession,
    user: User,
    rule_id: uuid.UUID,
    *,
    api_token: UserAPIToken | None = None,
) -> EventDeliveryRead:
    rule = await repository.get_event_rule_by_id(session, rule_id)
    if rule is None:
        raise EventRuleNotFoundError("event rule not found")
    await ensure_can_manage_rule(session, user, rule)
    ensure_api_token_rule_access(api_token, rule)
    delivery = await create_rule_ping_delivery(
        session,
        rule,
        actor_user_id=user.id,
        actor_token_id=api_token.id if api_token is not None and api_token.id else None,
        kind="test",
    )
    await session.refresh(delivery)
    event = await repository.get_event_record_by_id(session, delivery.event_record_id)
    return delivery_response(delivery, event=event)
