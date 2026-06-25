from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

PartnerStatus = Literal["none", "pending", "active", "suspended", "ended"]
PartnerTier = Literal["official", "supported", "verified", "community"]
SupportLevel = Literal["official", "verified", "compatible", "deprecated"]
SupportStatus = Literal["active", "pending", "suspended", "ended"]


class PartnerOrganizationUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    is_partner: bool | None = Field(default=None, alias="isPartner")
    partner_status: PartnerStatus | None = Field(default=None, alias="partnerStatus")
    partner_tier: PartnerTier | None = Field(default=None, alias="partnerTier")
    partner_support_level: SupportLevel | None = Field(default=None, alias="partnerSupportLevel")
    website_url: str | None = Field(default=None, alias="websiteUrl", max_length=2048)
    support_email: EmailStr | None = Field(default=None, alias="supportEmail")
    partner_profile: dict[str, Any] | None = Field(default=None, alias="partnerProfile")
    partner_internal_notes: str | None = Field(
        default=None,
        alias="partnerInternalNotes",
        max_length=10000,
    )


class PartnerOrganizationRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    name: str
    slug: str
    status: str
    is_partner: bool = Field(alias="isPartner")
    partner_status: PartnerStatus = Field(alias="partnerStatus")
    partner_tier: PartnerTier = Field(alias="partnerTier")
    partner_support_level: SupportLevel = Field(alias="partnerSupportLevel")
    website_url: str = Field(alias="websiteUrl")
    support_email: str = Field(alias="supportEmail")
    partner_profile: dict[str, Any] = Field(alias="partnerProfile")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class PartnerOrganizationListResponse(BaseModel):
    organizations: list[PartnerOrganizationRead]


class PartnerServerSupportCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    server_name: str = Field(alias="serverName", min_length=1, max_length=200)
    support_level: SupportLevel = Field(default="compatible", alias="supportLevel")
    support_status: SupportStatus = Field(default="pending", alias="supportStatus")
    support_url: str = Field(default="", alias="supportUrl", max_length=2048)
    docs_url: str = Field(default="", alias="docsUrl", max_length=2048)
    contact_policy: dict[str, Any] = Field(default_factory=dict, alias="contactPolicy")
    starts_at: datetime | None = Field(default=None, alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    internal_notes: str = Field(default="", alias="internalNotes", max_length=10000)


class PartnerServerSupportUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    support_level: SupportLevel | None = Field(default=None, alias="supportLevel")
    support_status: SupportStatus | None = Field(default=None, alias="supportStatus")
    support_url: str | None = Field(default=None, alias="supportUrl", max_length=2048)
    docs_url: str | None = Field(default=None, alias="docsUrl", max_length=2048)
    contact_policy: dict[str, Any] | None = Field(default=None, alias="contactPolicy")
    starts_at: datetime | None = Field(default=None, alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    internal_notes: str | None = Field(default=None, alias="internalNotes", max_length=10000)


class PartnerServerSupportRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    organization_id: UUID = Field(alias="organizationId")
    server_name: str = Field(alias="serverName")
    support_level: SupportLevel = Field(alias="supportLevel")
    support_status: SupportStatus = Field(alias="supportStatus")
    support_url: str = Field(alias="supportUrl")
    docs_url: str = Field(alias="docsUrl")
    contact_policy: dict[str, Any] = Field(alias="contactPolicy")
    starts_at: datetime | None = Field(default=None, alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class PartnerServerSupportListResponse(BaseModel):
    support: list[PartnerServerSupportRead]
