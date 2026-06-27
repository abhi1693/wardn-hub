import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr

APITokenScope = Literal[
    "audit:read",
    "catalog:read",
    "events:read",
    "events:write",
    "namespaces:write",
    "partners:write",
    "registry:write",
    "submissions:read",
    "submissions:write",
    "submissions:moderate",
    "submissions:publish",
    "tokens:read",
    "tokens:write",
    "users:read",
    "users:write",
]
AuthProviderKey = Literal["local", "clerk"]

DEFAULT_API_TOKEN_SCOPES: list[APITokenScope] = [
    "catalog:read",
    "submissions:read",
    "submissions:write",
]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    first_name: str
    last_name: str
    display_name: str
    is_active: bool
    is_superuser: bool
    is_global_moderator: bool
    is_global_partner_manager: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserDirectoryRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: uuid.UUID
    login: str
    name: str = ""
    avatar_url: str = Field(default="", alias="avatarUrl")
    html_url: str = Field(default="", alias="htmlUrl")
    email: EmailStr | None = None
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    display_name: str | None = Field(default=None, alias="displayName")
    is_active: bool | None = Field(default=None, alias="isActive")
    is_superuser: bool | None = Field(default=None, alias="isSuperuser")
    is_global_moderator: bool | None = Field(default=None, alias="isGlobalModerator")
    is_global_partner_manager: bool | None = Field(
        default=None,
        alias="isGlobalPartnerManager",
    )
    last_login_at: datetime | None = Field(default=None, alias="lastLoginAt")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")


class UserDirectoryListResponse(BaseModel):
    users: list[UserDirectoryRead]


class UserCreate(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=8)
    first_name: str = Field(default="", max_length=150)
    last_name: str = Field(default="", max_length=150)


class BootstrapUserCreate(UserCreate):
    pass


class UserAdminUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    is_active: bool | None = Field(default=None, alias="isActive")
    is_superuser: bool | None = Field(default=None, alias="isSuperuser")
    is_global_moderator: bool | None = Field(default=None, alias="isGlobalModerator")
    is_global_partner_manager: bool | None = Field(
        default=None,
        alias="isGlobalPartnerManager",
    )


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr


class AuthProviderRead(BaseModel):
    provider: AuthProviderKey
    label: str
    sign_in_enabled: bool = Field(alias="signInEnabled")
    sign_up_enabled: bool = Field(alias="signUpEnabled")


class AuthProviderListResponse(BaseModel):
    default_provider: AuthProviderKey = Field(alias="defaultProvider")
    providers: list[AuthProviderRead]


class UserAPITokenCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=200)
    scopes: list[APITokenScope] = Field(default_factory=lambda: DEFAULT_API_TOKEN_SCOPES.copy())
    expires_at: datetime | None = None
    organization_ids: list[uuid.UUID] = Field(default_factory=list, alias="organizationIds")


class UserAPITokenUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=200)
    scopes: list[APITokenScope] | None = None
    expires_at: datetime | None = None
    organization_ids: list[uuid.UUID] | None = Field(default=None, alias="organizationIds")
    is_active: bool | None = None


class UserAPITokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str
    token_prefix: str
    scopes: list[APITokenScope]
    organization_ids: list[uuid.UUID] = Field(alias="organizationIds")
    is_active: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserAPITokenCreated(BaseModel):
    token: str
    record: UserAPITokenRead


class UserAPITokenListResponse(BaseModel):
    tokens: list[UserAPITokenRead]
