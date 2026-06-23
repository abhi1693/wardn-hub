from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

MCP_SERVER_NAME_PATTERN = r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$"
RegistryServerStatus = Literal["active", "deprecated", "deleted", "quarantined"]
RegistryVersionStatus = Literal["active", "deprecated", "deleted", "quarantined", "rejected"]
RegistryVisibility = Literal["public", "unlisted", "private_preview"]


class MCPServerDocument(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_uri: str = Field(
        alias="$schema",
        min_length=1,
        examples=["https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"],
    )
    name: str = Field(min_length=3, max_length=200, pattern=MCP_SERVER_NAME_PATTERN)
    description: str = Field(min_length=1)
    title: str = Field(default="", max_length=100)
    repository: dict[str, Any] | None = None
    version: str = Field(min_length=1, max_length=255)
    website_url: str = Field(default="", alias="websiteUrl", max_length=2048)
    icons: list[dict[str, Any]] = Field(default_factory=list)
    packages: list[dict[str, Any]] = Field(default_factory=list)
    remotes: list[dict[str, Any]] = Field(default_factory=list)
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")

    @field_validator("website_url")
    @classmethod
    def validate_website_url(cls, value: str) -> str:
        if value:
            HttpUrl(value)
        return value

    @model_validator(mode="after")
    def require_package_or_remote(self) -> "MCPServerDocument":
        if not self.packages and not self.remotes:
            raise ValueError("at least one package or remote target is required")
        return self


class RegistryServerVersionCreate(MCPServerDocument):
    pass


class RegistryServerVersionUpdate(MCPServerDocument):
    pass


class ActorSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    login: str
    type: Literal["User", "Organization"]
    name: str = ""
    avatar_url: str = Field(default="", alias="avatarUrl")
    url: str = ""
    html_url: str = Field(default="", alias="htmlUrl")


class RegistryLatestVersionSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    version: str
    status: RegistryVersionStatus
    published_at: datetime = Field(alias="publishedAt")
    published_by: ActorSummary | None = Field(default=None, alias="publishedBy")


class RegistryServerRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    name: str
    title: str
    description: str
    website_url: str = Field(alias="websiteUrl")
    repository: dict[str, Any] | None = None
    icons: list[dict[str, Any]] = Field(default_factory=list)
    status: RegistryServerStatus
    status_message: str = Field(alias="statusMessage")
    visibility: RegistryVisibility
    owner: ActorSummary | None = None
    organization: ActorSummary | None = None
    created_by: ActorSummary | None = Field(default=None, alias="createdBy")
    updated_by: ActorSummary | None = Field(default=None, alias="updatedBy")
    latest_version: RegistryLatestVersionSummary | None = Field(default=None, alias="latestVersion")
    partner_support: dict[str, Any] | None = Field(default=None, alias="partnerSupport")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class RegistryServerVersionRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    server_id: UUID = Field(alias="serverId")
    name: str
    version: str
    title: str
    description: str
    website_url: str = Field(alias="websiteUrl")
    repository: dict[str, Any] | None = None
    packages: list[dict[str, Any]] = Field(default_factory=list)
    remotes: list[dict[str, Any]] = Field(default_factory=list)
    icons: list[dict[str, Any]] = Field(default_factory=list)
    server_json: dict[str, Any] = Field(alias="serverJson")
    status: RegistryVersionStatus
    status_message: str = Field(alias="statusMessage")
    is_latest: bool = Field(alias="isLatest")
    owner: ActorSummary | None = None
    organization: ActorSummary | None = None
    created_by: ActorSummary | None = Field(default=None, alias="createdBy")
    updated_by: ActorSummary | None = Field(default=None, alias="updatedBy")
    published_by: ActorSummary | None = Field(default=None, alias="publishedBy")
    approver: ActorSummary | None = None
    published_at: datetime = Field(alias="publishedAt")
    status_changed_at: datetime = Field(alias="statusChangedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class RegistryListMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    count: int
    next_cursor: str = Field(default="", alias="nextCursor")


class RegistryServerListResponse(BaseModel):
    servers: list[RegistryServerRead]
    metadata: RegistryListMetadata


class RegistryServerVersionListResponse(BaseModel):
    versions: list[RegistryServerVersionRead]
    metadata: RegistryListMetadata


class RegistryServerDetailResponse(BaseModel):
    server: RegistryServerRead
    versions: list[RegistryServerVersionRead] = Field(default_factory=list)


class RegistryServerVersionDetailResponse(BaseModel):
    server: RegistryServerRead
    version: RegistryServerVersionRead
    support: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None

