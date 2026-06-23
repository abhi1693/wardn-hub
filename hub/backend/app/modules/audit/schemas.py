from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuditEventRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    actor_user_id: UUID | None = Field(default=None, alias="actorUserId")
    actor_token_id: UUID | None = Field(default=None, alias="actorTokenId")
    organization_id: UUID | None = Field(default=None, alias="organizationId")
    event_type: str = Field(alias="eventType")
    subject_type: str = Field(alias="subjectType")
    subject_id: str = Field(alias="subjectId")
    ip_address: str = Field(alias="ipAddress")
    user_agent: str = Field(alias="userAgent")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(alias="createdAt")


class AuditEventListResponse(BaseModel):
    events: list[AuditEventRead]
