from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditEvent


async def list_audit_events(session: AsyncSession, *, limit: int) -> list[AuditEvent]:
    result = await session.execute(
        select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit)
    )
    return list(result.scalars().all())
