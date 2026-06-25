from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

MCP_SERVER_NAME_PATTERN = r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$"
SEMVER_PATTERN = (
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
RegistryServerStatus = Literal["active", "deprecated", "deleted", "quarantined"]
RegistryVersionStatus = Literal["active", "deprecated", "deleted", "quarantined", "rejected"]
RegistryVisibility = Literal["public", "unlisted", "private_preview"]


class RegistryRepository(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    source: str = Field(default="", examples=["github"])
    type_: str = Field(default="", alias="type", examples=["git"])
    url: str = Field(default="", max_length=2048, examples=["https://github.com/acme/weather-mcp"])
    subfolder: str = Field(default="", max_length=500, examples=["packages/server"])
    branch: str = Field(default="", examples=["main"])
    tag: str = Field(default="", examples=["v1.0.0"])


class RegistryIcon(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    src: str = Field(default="", max_length=2048, examples=["https://github.com/acme.png"])
    type_: str = Field(default="", alias="type", examples=["image/png"])
    sizes: str | list[str] = Field(default="", examples=["512x512"])


class RegistryTransport(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    type_: str = Field(default="", alias="type", examples=["stdio"])
    command: str = Field(default="", examples=["npx"])
    args: list[str] = Field(default_factory=list, examples=[["-y", "@acme/weather-mcp"]])
    env: dict[str, Any] = Field(default_factory=dict)


class RegistryPackage(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    registry_type: str = Field(default="", alias="registryType", examples=["npm"])
    identifier: str = Field(default="", examples=["@acme/weather-mcp"])
    version: str = Field(default="", examples=["1.0.0"])
    transport: RegistryTransport | None = None


class RegistryRemoteHeader(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str = Field(default="", examples=["Authorization"])
    value: str = Field(default="", examples=["Bearer ${WEATHER_API_TOKEN}"])
    required: bool = True
    secret: bool = True


class RegistryRemote(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    type_: str = Field(default="", alias="type", examples=["streamable-http"])
    url: str = Field(default="", max_length=2048, examples=["https://weather.example.com/mcp"])
    headers: list[RegistryRemoteHeader] = Field(default_factory=list)
    authentication: dict[str, Any] = Field(default_factory=dict)


class MCPServerDocument(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "$schema": (
                        "https://static.modelcontextprotocol.io/schemas/2025-12-11/"
                        "server.schema.json"
                    ),
                    "name": "io.github.acme/weather-mcp",
                    "title": "Weather MCP",
                    "description": "Weather forecast tools for MCP clients.",
                    "documentation": (
                        "## Overview\nWeather MCP provides forecast and alert tools.\n\n"
                        "## Configuration\nSet WEATHER_API_TOKEN before starting the server."
                    ),
                    "repository": {
                        "type": "git",
                        "source": "github",
                        "url": "https://github.com/acme/weather-mcp",
                    },
                    "version": "1.0.0",
                    "websiteUrl": "https://github.com/acme/weather-mcp#readme",
                    "icons": [{"src": "https://github.com/acme.png", "type": "image/png"}],
                    "packages": [
                        {
                            "registryType": "npm",
                            "identifier": "@acme/weather-mcp",
                            "version": "1.0.0",
                            "transport": {
                                "type": "stdio",
                                "command": "npx",
                                "args": ["-y", "@acme/weather-mcp"],
                            },
                        }
                    ],
                    "remotes": [],
                    "_meta": {
                        "categories": ["weather"],
                        "source": {"readme": "README.md"},
                    },
                }
            ]
        },
    )

    schema_uri: str = Field(
        alias="$schema",
        min_length=1,
        examples=["https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"],
    )
    name: str = Field(min_length=3, max_length=200, pattern=MCP_SERVER_NAME_PATTERN)
    description: str = Field(min_length=1)
    documentation: str = ""
    title: str = Field(default="", max_length=100)
    repository: RegistryRepository | None = None
    version: str = Field(min_length=1, max_length=255, pattern=SEMVER_PATTERN)
    website_url: str = Field(default="", alias="websiteUrl", max_length=2048)
    icons: list[RegistryIcon] = Field(default_factory=list)
    packages: list[RegistryPackage] = Field(default_factory=list)
    remotes: list[RegistryRemote] = Field(default_factory=list)
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


class PartnerSupportSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    organization: ActorSummary
    support_level: Literal["official", "verified", "compatible", "deprecated"] = Field(
        alias="supportLevel"
    )
    support_status: Literal["active", "pending", "suspended", "ended"] = Field(
        alias="supportStatus"
    )
    support_url: str = Field(alias="supportUrl")
    docs_url: str = Field(alias="docsUrl")
    starts_at: datetime | None = Field(default=None, alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")


class RegistryCategoryRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    slug: str
    name: str
    description: str = ""
    sort_order: int = Field(alias="sortOrder")


class RegistryServerRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    name: str
    title: str
    description: str
    documentation: str = ""
    website_url: str = Field(alias="websiteUrl")
    repository: RegistryRepository | None = None
    icons: list[RegistryIcon] = Field(default_factory=list)
    status: RegistryServerStatus
    status_message: str = Field(alias="statusMessage")
    visibility: RegistryVisibility
    owner: ActorSummary | None = None
    organization: ActorSummary | None = None
    created_by: ActorSummary | None = Field(default=None, alias="createdBy")
    updated_by: ActorSummary | None = Field(default=None, alias="updatedBy")
    latest_version: RegistryLatestVersionSummary | None = Field(default=None, alias="latestVersion")
    categories: list[RegistryCategoryRead] = Field(default_factory=list)
    partner_support: list[PartnerSupportSummary] = Field(
        default_factory=list,
        alias="partnerSupport",
    )
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
    documentation: str = ""
    website_url: str = Field(alias="websiteUrl")
    repository: RegistryRepository | None = None
    packages: list[RegistryPackage] = Field(default_factory=list)
    remotes: list[RegistryRemote] = Field(default_factory=list)
    icons: list[RegistryIcon] = Field(default_factory=list)
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
    categories: list[RegistryCategoryRead] = Field(default_factory=list)
    partner_support: list[PartnerSupportSummary] = Field(
        default_factory=list,
        alias="partnerSupport",
    )
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


class RegistryUserRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    login: str
    name: str = ""
    avatar_url: str = Field(default="", alias="avatarUrl")
    html_url: str = Field(default="", alias="htmlUrl")


class RegistryUserListResponse(BaseModel):
    users: list[RegistryUserRead]


class RegistryUserDetailResponse(BaseModel):
    user: RegistryUserRead
    servers: list[RegistryServerRead]
    metadata: RegistryListMetadata


class RegistryCategoryListResponse(BaseModel):
    categories: list[RegistryCategoryRead]


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
