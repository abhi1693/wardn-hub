from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

NamespaceClaimMethod = Literal["github", "dns", "http", "manual_partner", "imported_official"]
NamespaceClaimStatus = Literal["pending", "verified", "failed", "revoked"]


def normalize_namespace(value: str) -> str:
    namespace = value.strip().casefold()
    if namespace.endswith("/*"):
        return namespace
    if namespace.endswith("/"):
        namespace = namespace[:-1]
    return f"{namespace}/*"


def is_valid_namespace(value: str) -> bool:
    if not value.endswith("/*"):
        return False
    prefix = value[:-2]
    labels = prefix.split(".")
    if len(labels) < 2:
        return False
    if any(not label or label.startswith("-") or label.endswith("-") for label in labels):
        return False
    if any(not all(char.isalnum() or char == "-" for char in label) for label in labels):
        return False
    if labels[:2] == ["io", "github"]:
        return len(labels) == 3
    return len(labels) >= 2


class NamespaceClaimCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    namespace: str = Field(min_length=3, max_length=255)
    owner_organization_id: UUID | None = Field(default=None, alias="ownerOrganizationId")
    method: NamespaceClaimMethod = "github"
    verification_payload: dict[str, Any] = Field(default_factory=dict, alias="verificationPayload")
    expires_at: datetime | None = Field(default=None, alias="expiresAt")

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, value: str) -> str:
        namespace = normalize_namespace(value)
        if not is_valid_namespace(namespace):
            raise ValueError(
                "namespace must be io.github.owner/* or reverse-DNS like com.example/*"
            )
        return namespace


class NamespaceClaimDecision(BaseModel):
    verification_payload: dict[str, Any] = Field(default_factory=dict, alias="verificationPayload")


class NamespaceClaimRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    namespace: str
    owner_organization_id: UUID | None = Field(default=None, alias="ownerOrganizationId")
    claimed_by_user_id: UUID = Field(alias="claimedByUserId")
    method: NamespaceClaimMethod
    status: NamespaceClaimStatus
    verification_payload: dict[str, Any] = Field(alias="verificationPayload")
    verified_at: datetime | None = Field(default=None, alias="verifiedAt")
    expires_at: datetime | None = Field(default=None, alias="expiresAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class NamespaceClaimListResponse(BaseModel):
    claims: list[NamespaceClaimRead]
