from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.registry.schemas import RegistryServerVersionCreate

SubmissionStatus = Literal["draft", "submitted", "approved", "rejected", "withdrawn", "published"]
SubmissionType = Literal["new_server", "new_version", "metadata_edit", "takedown_appeal"]


class SubmissionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    submission_type: SubmissionType = Field(default="new_server", alias="submissionType")
    owner_user_id: UUID | None = Field(default=None, alias="ownerUserId")
    owner_organization_id: UUID | None = Field(default=None, alias="ownerOrganizationId")
    server_json: RegistryServerVersionCreate = Field(alias="serverJson")

    @model_validator(mode="after")
    def new_servers_start_at_initial_version(self) -> "SubmissionCreate":
        if self.submission_type == "new_server" and self.server_json.version != "1.0.0":
            raise ValueError("new server submissions must start at version 1.0.0")
        return self


class SubmissionUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    submission_type: SubmissionType | None = Field(default=None, alias="submissionType")
    owner_user_id: UUID | None = Field(default=None, alias="ownerUserId")
    owner_organization_id: UUID | None = Field(default=None, alias="ownerOrganizationId")
    server_json: RegistryServerVersionCreate | None = Field(default=None, alias="serverJson")


class SubmissionRejectRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class SubmissionRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    name: str
    version: str
    submitter_user_id: UUID = Field(alias="submitterUserId")
    owner_user_id: UUID | None = Field(default=None, alias="ownerUserId")
    owner_organization_id: UUID | None = Field(default=None, alias="ownerOrganizationId")
    submission_type: SubmissionType = Field(alias="submissionType")
    status: SubmissionStatus
    server_json: dict[str, Any] = Field(alias="serverJson")
    validation_result: dict[str, Any] = Field(alias="validationResult")
    submitted_at: datetime | None = Field(default=None, alias="submittedAt")
    approved_at: datetime | None = Field(default=None, alias="approvedAt")
    approver_user_id: UUID | None = Field(default=None, alias="approverUserId")
    rejection_message: str = Field(alias="rejectionMessage")
    published_server_version_id: UUID | None = Field(default=None, alias="publishedServerVersionId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class SubmissionListResponse(BaseModel):
    submissions: list[SubmissionRead]
