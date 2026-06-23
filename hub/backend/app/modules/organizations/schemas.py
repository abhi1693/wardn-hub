from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

OrganizationStatus = Literal["active", "suspended", "archived"]


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9-]*$")


class OrganizationUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    status: OrganizationStatus = "active"


class OrganizationRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    name: str
    slug: str
    status: str
    current_user_role: str = Field(alias="currentUserRole")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class OrganizationListResponse(BaseModel):
    organizations: list[OrganizationRead]


class OrganizationRoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str = Field(default="", max_length=2000)
    permissions: list[str] = Field(default_factory=list)


class OrganizationRoleRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    organization_id: UUID = Field(alias="organizationId")
    name: str
    slug: str
    description: str
    permissions: list[str]
    is_system_role: bool = Field(alias="isSystemRole")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class OrganizationRoleListResponse(BaseModel):
    roles: list[OrganizationRoleRead]


class OrganizationMembershipCreate(BaseModel):
    user_id: UUID = Field(alias="userId")
    role_slug: str = Field(alias="roleSlug", min_length=1, max_length=100)


class OrganizationMembershipUpdate(BaseModel):
    role_slug: str = Field(alias="roleSlug", min_length=1, max_length=100)
    is_active: bool = Field(default=True, alias="isActive")


class OrganizationMembershipRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    organization_id: UUID = Field(alias="organizationId")
    user_id: UUID = Field(alias="userId")
    role_id: UUID = Field(alias="roleId")
    role_slug: str = Field(alias="roleSlug")
    permissions: list[str]
    is_active: bool = Field(alias="isActive")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class OrganizationMembershipListResponse(BaseModel):
    memberships: list[OrganizationMembershipRead]

