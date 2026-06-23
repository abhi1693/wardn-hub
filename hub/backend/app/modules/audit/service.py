import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import repository
from app.modules.audit.models import AuditEvent
from app.modules.audit.schemas import AuditEventListResponse, AuditEventRead


def audit_event_response(event: AuditEvent) -> AuditEventRead:
    return AuditEventRead(
        id=event.id,
        actorUserId=event.actor_user_id,
        actorTokenId=event.actor_token_id,
        organizationId=event.organization_id,
        eventType=event.event_type,
        subjectType=event.subject_type,
        subjectId=event.subject_id,
        ipAddress=event.ip_address,
        userAgent=event.user_agent,
        metadata=event.metadata_,
        createdAt=event.created_at,
    )


async def emit_audit_event(
    session: AsyncSession,
    *,
    event_type: str,
    subject_type: str,
    subject_id: str | uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
    actor_token_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str = "",
    user_agent: str = "",
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        organization_id=organization_id,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=str(subject_id),
        ip_address=ip_address,
        user_agent=user_agent,
        metadata_=metadata or {},
    )
    session.add(event)
    await session.flush()
    return event


async def list_events(session: AsyncSession, *, limit: int) -> AuditEventListResponse:
    events = await repository.list_audit_events(session, limit=limit)
    return AuditEventListResponse(events=[audit_event_response(event) for event in events])
