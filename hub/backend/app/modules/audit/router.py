from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.modules.audit.schemas import AuditEventListResponse
from app.modules.audit.service import list_events
from app.modules.users.dependencies import require_superuser_scopes
from app.modules.users.models import User

router = APIRouter(prefix="/audit/events", tags=["audit"])


@router.get("", response_model=AuditEventListResponse, operation_id="audit_events_list")
async def list_audit_events(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _current_user: Annotated[User, Depends(require_superuser_scopes("audit:read"))],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditEventListResponse:
    return await list_events(session, limit=limit)
