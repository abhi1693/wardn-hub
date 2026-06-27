import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EventActionType = Literal["webhook"]
EventDeliveryStatus = Literal[
    "pending",
    "running",
    "succeeded",
    "failed",
    "retrying",
    "disabled",
    "cancelled",
]


class EventTypeRead(BaseModel):
    event_type: str = Field(alias="eventType")
    label: str
    description: str
    subject_type: str = Field(alias="subjectType")


class EventTypeListResponse(BaseModel):
    event_types: list[EventTypeRead] = Field(alias="eventTypes")


class EventRuleBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    owner_user_id: uuid.UUID | None = Field(default=None, alias="ownerUserId")
    owner_organization_id: uuid.UUID | None = Field(default=None, alias="ownerOrganizationId")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    is_enabled: bool = Field(default=True, alias="isEnabled")
    event_types: list[str] = Field(alias="eventTypes", min_length=1)
    conditions: dict[str, Any] = Field(default_factory=dict)
    action_type: EventActionType = Field(default="webhook", alias="actionType")
    action_config: dict[str, Any] = Field(alias="actionConfig")
    failure_policy: dict[str, Any] = Field(default_factory=dict, alias="failurePolicy")

    @field_validator("event_types")
    @classmethod
    def event_types_are_unique(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("eventTypes must not contain duplicates")
        if not normalized:
            raise ValueError("eventTypes must not be empty")
        return normalized


class EventRuleCreate(EventRuleBase):
    pass


class EventRuleUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    owner_user_id: uuid.UUID | None = Field(default=None, alias="ownerUserId")
    owner_organization_id: uuid.UUID | None = Field(default=None, alias="ownerOrganizationId")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    is_enabled: bool | None = Field(default=None, alias="isEnabled")
    event_types: list[str] | None = Field(default=None, alias="eventTypes", min_length=1)
    conditions: dict[str, Any] | None = None
    action_type: EventActionType | None = Field(default=None, alias="actionType")
    action_config: dict[str, Any] | None = Field(default=None, alias="actionConfig")
    failure_policy: dict[str, Any] | None = Field(default=None, alias="failurePolicy")

    @field_validator("event_types")
    @classmethod
    def event_types_are_unique(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [item.strip() for item in value if item.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("eventTypes must not contain duplicates")
        if not normalized:
            raise ValueError("eventTypes must not be empty")
        return normalized


class EventRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    owner_user_id: uuid.UUID | None = Field(alias="ownerUserId")
    owner_organization_id: uuid.UUID | None = Field(alias="ownerOrganizationId")
    created_by_user_id: uuid.UUID | None = Field(alias="createdByUserId")
    name: str
    description: str
    is_enabled: bool = Field(alias="isEnabled")
    event_types: list[str] = Field(alias="eventTypes")
    conditions: dict[str, Any]
    action_type: str = Field(alias="actionType")
    action_config: dict[str, Any] = Field(alias="actionConfig")
    failure_policy: dict[str, Any] = Field(alias="failurePolicy")
    last_triggered_at: datetime | None = Field(alias="lastTriggeredAt")
    signing_secret: str | None = Field(default=None, alias="signingSecret")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class EventRuleListResponse(BaseModel):
    rules: list[EventRuleRead]


class EventSecretRotateResponse(BaseModel):
    rule: EventRuleRead
    signing_secret: str = Field(alias="signingSecret")


class EventRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    event_type: str = Field(alias="eventType")
    subject_type: str = Field(alias="subjectType")
    subject_id: str = Field(alias="subjectId")
    actor_user_id: uuid.UUID | None = Field(alias="actorUserId")
    actor_token_id: uuid.UUID | None = Field(alias="actorTokenId")
    owner_user_id: uuid.UUID | None = Field(alias="ownerUserId")
    owner_organization_id: uuid.UUID | None = Field(alias="ownerOrganizationId")
    visibility_scope: str = Field(alias="visibilityScope")
    payload: dict[str, Any]
    processed_at: datetime | None = Field(alias="processedAt")
    created_at: datetime = Field(alias="createdAt")


class EventDeliveryEventSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: uuid.UUID
    event_type: str = Field(alias="eventType")
    subject_type: str = Field(alias="subjectType")
    subject_id: str = Field(alias="subjectId")
    subject_label: str = Field(alias="subjectLabel")
    subject_version: str = Field(default="", alias="subjectVersion")
    occurred_at: str = Field(default="", alias="occurredAt")


class EventDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    event_record_id: uuid.UUID = Field(alias="eventRecordId")
    event: EventDeliveryEventSummary | None = None
    event_rule_id: uuid.UUID | None = Field(alias="eventRuleId")
    destination_type: str = Field(alias="destinationType")
    destination_url_redacted: str = Field(alias="destinationUrlRedacted")
    status: str
    attempt_count: int = Field(alias="attemptCount")
    next_attempt_at: datetime | None = Field(alias="nextAttemptAt")
    last_attempt_at: datetime | None = Field(alias="lastAttemptAt")
    response_status: int | None = Field(alias="responseStatus")
    response_body: str = Field(alias="responseBody")
    error_message: str = Field(alias="errorMessage")
    request_headers: dict[str, Any] = Field(alias="requestHeaders")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class EventDeliveryListResponse(BaseModel):
    deliveries: list[EventDeliveryRead]
