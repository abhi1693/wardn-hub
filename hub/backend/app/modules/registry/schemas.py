from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

MCP_SERVER_NAME_PATTERN = r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$"
SEMVER_PATTERN = (
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
RegistryServerStatus = Literal["active", "deprecated", "deleted", "quarantined"]
RegistryVersionStatus = Literal["active", "deprecated", "deleted", "quarantined", "rejected"]
RegistryVisibility = Literal["public", "unlisted", "private_preview"]
RegistryNamespaceType = Literal["github", "domain", "unknown"]
RegistryNamespaceVerificationStatus = Literal[
    "verified",
    "unverified",
    "imported",
    "conflict",
    "unknown",
]
CATEGORY_SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
PUBLISHER_META_KEY = "io.modelcontextprotocol.registry/publisher-provided"
ARGUMENT_VALUE_PLACEHOLDER_PATTERN = re.compile(
    r"^(?P<flag>.*?)(?:\s*(?:=\s*)?<(?P<angle>[^<>]+)>|\s+\[(?P<bracket>[^\[\]]+)\])$"
)
ARGUMENT_PLACEHOLDER_VALUE_PATTERN = re.compile(r"^(?:<[^<>]+>|\[[^\[\]]+\])$")
REMOTE_QUERY_PARAMETER_ALIASES = (
    "queryParameters",
    "queryParams",
    "query_parameters",
    "query_params",
)
REMOTE_QUERY_VALUE_PLACEHOLDER_PATTERN = re.compile(r"^(?:\{([^{}]+)\}|<([^<>]+)>|\[([^\[\]]+)\])$")


def split_argument_value_placeholder(flag: str) -> tuple[str, bool]:
    match = ARGUMENT_VALUE_PLACEHOLDER_PATTERN.match(flag.strip())
    if not match:
        return flag, False
    return match.group("flag").strip(), True


def metadata_has_category(metadata: dict[str, Any] | None) -> bool:
    if not isinstance(metadata, dict):
        return False
    for source in (metadata, metadata.get(PUBLISHER_META_KEY, {})):
        if not isinstance(source, dict):
            continue
        if isinstance(source.get("category"), str) and source["category"].strip():
            return True
        categories = source.get("categories")
        if isinstance(categories, list) and any(
            isinstance(value, str) and value.strip() for value in categories
        ):
            return True
    return False


def normalize_remote_query_parameter(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    parameter = dict(value)
    name = parameter.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    parameter["name"] = name.strip()

    if "required" in parameter and "isRequired" not in parameter:
        parameter["isRequired"] = parameter.pop("required")
    if "secret" in parameter and "isSecret" not in parameter:
        parameter["isSecret"] = parameter.pop("secret")

    return parameter


def query_parameter_from_url(name: str, value: str) -> dict[str, Any] | None:
    if not name.strip():
        return None

    parameter: dict[str, Any] = {
        "name": name.strip(),
        "value": value,
        "isRequired": True,
        "isSecret": False,
    }
    if REMOTE_QUERY_VALUE_PLACEHOLDER_PATTERN.match(value.strip()):
        parameter["value"] = ""
        parameter["isSecret"] = True
    return parameter


def remote_query_parameters_from_value(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    parameters = []
    for parameter in value:
        normalized = normalize_remote_query_parameter(parameter)
        if normalized:
            parameters.append(normalized)
    return parameters


def normalize_remote_mapping(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    remote = dict(value)
    query_parameters: list[dict[str, Any]] = []
    seen_parameter_names: set[str] = set()
    has_query_parameter_field = False

    def add_parameters(parameters: list[dict[str, Any]]) -> None:
        for parameter in parameters:
            name = str(parameter.get("name") or "").strip()
            if not name or name in seen_parameter_names:
                continue
            seen_parameter_names.add(name)
            query_parameters.append(parameter)

    for alias in REMOTE_QUERY_PARAMETER_ALIASES:
        if alias in remote:
            has_query_parameter_field = True
            add_parameters(remote_query_parameters_from_value(remote.pop(alias, None)))

    authentication = remote.get("authentication")
    if isinstance(authentication, dict):
        authentication = dict(authentication)
        for alias in REMOTE_QUERY_PARAMETER_ALIASES:
            if alias in authentication:
                has_query_parameter_field = True
                add_parameters(remote_query_parameters_from_value(authentication.pop(alias, None)))
        remote["authentication"] = authentication

    url = remote.get("url")
    if isinstance(url, str) and url.strip():
        parsed_url = urlsplit(url.strip())
        url_query_parameters = [
            parameter
            for parameter in (
                query_parameter_from_url(name, value)
                for name, value in parse_qsl(parsed_url.query, keep_blank_values=True)
            )
            if parameter is not None
        ]
        if url_query_parameters:
            has_query_parameter_field = True
        add_parameters(url_query_parameters)
        if query_parameters and parsed_url.query:
            remote["url"] = urlunsplit(
                (
                    parsed_url.scheme,
                    parsed_url.netloc,
                    parsed_url.path,
                    "",
                    parsed_url.fragment,
                )
            )

    if query_parameters or has_query_parameter_field:
        remote["queryParameters"] = query_parameters
    return remote


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


class RegistryEnvironmentVariable(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str = Field(default="", examples=["WEATHER_API_TOKEN"])
    description: str = Field(default="", examples=["API token used by the weather service."])
    value: str = Field(default="", examples=[""])
    default: str = Field(default="", examples=[""])
    format: str = Field(default="string", examples=["string"])
    is_required: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("isRequired", "is_required", "required"),
        serialization_alias="isRequired",
    )
    is_secret: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("isSecret", "is_secret", "secret"),
        serialization_alias="isSecret",
    )


class RegistryPackageArgument(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str = Field(default="", examples=["port"])
    flag: str = Field(default="", examples=["--port"])
    value: str = Field(default="", examples=[""])
    default: str = Field(default="", examples=[""])
    description: str = Field(default="", examples=["Port for the local HTTP server."])
    format: str = Field(default="string", examples=["integer"])
    requires_value: bool = Field(
        default=False,
        validation_alias=AliasChoices("requiresValue", "requires_value"),
        serialization_alias="requiresValue",
    )
    include_in_launch: bool = Field(
        default=False,
        validation_alias=AliasChoices("includeInLaunch", "include_in_launch", "includeInCommand"),
        serialization_alias="includeInLaunch",
    )
    options: list[str] = Field(default_factory=list)
    allowed_values: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("allowedValues", "allowed_values"),
        serialization_alias="allowedValues",
    )
    is_required: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("isRequired", "is_required", "required"),
        serialization_alias="isRequired",
    )
    is_secret: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("isSecret", "is_secret", "secret"),
        serialization_alias="isSecret",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_value_placeholder(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized_data = {**data}
        flag = data.get("flag")
        flag_requires_value = False
        if isinstance(flag, str) and flag.strip():
            normalized_flag, flag_requires_value = split_argument_value_placeholder(flag)
            normalized_data["flag"] = normalized_flag

        value = data.get("value")
        value_requires_value = (
            isinstance(value, str) and bool(ARGUMENT_PLACEHOLDER_VALUE_PATTERN.match(value.strip()))
        )
        if value_requires_value:
            normalized_data["value"] = ""

        for key in ("valueName", "value_name", "placeholder"):
            normalized_data.pop(key, None)

        if flag_requires_value or value_requires_value:
            normalized_data["requiresValue"] = True
        return normalized_data


class RegistryPackage(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    registry_type: str = Field(
        default="",
        validation_alias=AliasChoices("registryType", "registry_type"),
        serialization_alias="registryType",
        examples=["npm"],
    )
    registry_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("registryBaseUrl", "registry_base_url"),
        serialization_alias="registryBaseUrl",
        examples=["https://registry.npmjs.org"],
    )
    identifier: str = Field(default="", examples=["@acme/weather-mcp"])
    version: str = Field(default="", examples=["1.0.0"])
    runtime_hint: str = Field(
        default="",
        validation_alias=AliasChoices("runtimeHint", "runtime_hint"),
        serialization_alias="runtimeHint",
        examples=["docker"],
    )
    transport: RegistryTransport | None = None
    environment_variables: list[RegistryEnvironmentVariable] = Field(
        default_factory=list,
        validation_alias=AliasChoices("environmentVariables", "environment_variables"),
        serialization_alias="environmentVariables",
    )
    package_arguments: list[RegistryPackageArgument] = Field(
        default_factory=list,
        validation_alias=AliasChoices("packageArguments", "package_arguments"),
        serialization_alias="packageArguments",
    )


class RegistryRemoteHeader(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str = Field(default="", examples=["Authorization"])
    value: str = Field(default="", examples=["Bearer ${WEATHER_API_TOKEN}"])
    description: str = Field(default="", examples=["Bearer token used by the remote MCP endpoint."])
    is_required: bool = Field(
        default=True,
        validation_alias=AliasChoices("isRequired", "is_required", "required"),
        serialization_alias="isRequired",
    )
    is_secret: bool = Field(
        default=True,
        validation_alias=AliasChoices("isSecret", "is_secret", "secret"),
        serialization_alias="isSecret",
    )


class RegistryRemoteQueryParameter(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str = Field(default="", examples=["api_key"])
    value: str = Field(default="", examples=["${WEATHER_API_TOKEN}"])
    description: str = Field(default="", examples=["API key passed to the remote MCP endpoint."])
    is_required: bool = Field(
        default=True,
        validation_alias=AliasChoices("isRequired", "is_required", "required"),
        serialization_alias="isRequired",
    )
    is_secret: bool = Field(
        default=True,
        validation_alias=AliasChoices("isSecret", "is_secret", "secret"),
        serialization_alias="isSecret",
    )


class RegistryRemote(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    type_: str = Field(default="", alias="type", examples=["streamable-http"])
    url: str = Field(default="", max_length=2048, examples=["https://weather.example.com/mcp"])
    headers: list[RegistryRemoteHeader] = Field(default_factory=list)
    query_parameters: list[RegistryRemoteQueryParameter] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "queryParameters",
            "queryParams",
            "query_parameters",
            "query_params",
        ),
        serialization_alias="queryParameters",
    )
    authentication: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_query_parameters(cls, data: Any) -> Any:
        return normalize_remote_mapping(data)


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
    def require_package_or_remote(self) -> MCPServerDocument:
        if not self.packages and not self.remotes:
            raise ValueError("at least one package or remote target is required")
        if not metadata_has_category(self.meta):
            raise ValueError("at least one category is required")
        return self

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class RegistryServerVersionCreate(MCPServerDocument):
    pass


class RegistryServerVersionUpdate(MCPServerDocument):
    pass


class RegistryCategoryCreate(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "slug": "automation",
                    "name": "Automation",
                    "description": "MCP servers for workflow automation.",
                    "sortOrder": 120,
                }
            ]
        },
    )

    slug: str = Field(min_length=1, max_length=80, pattern=CATEGORY_SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    sort_order: int | None = Field(default=None, ge=0, le=100000, alias="sortOrder")


class RegistryCategoryUpdate(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "slug": "automation",
                    "name": "Automation",
                    "description": "MCP servers for workflow automation and jobs.",
                    "sortOrder": 125,
                }
            ]
        },
    )

    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=CATEGORY_SLUG_PATTERN,
    )
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000, alias="sortOrder")


class ActorSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    login: str
    type: Literal["User", "Organization"]
    name: str = ""
    avatar_url: str = Field(default="", alias="avatarUrl")
    url: str = ""
    html_url: str = Field(default="", alias="htmlUrl")


class RegistryNamespace(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    namespace: str
    server: str
    type_: RegistryNamespaceType = Field(alias="type")
    authority: str = ""
    display_name: str = Field(default="", alias="displayName")
    verification_status: RegistryNamespaceVerificationStatus = Field(alias="verificationStatus")
    verification_method: str = Field(default="", alias="verificationMethod")
    evidence_url: str = Field(default="", alias="evidenceUrl")
    evidence_text: str = Field(default="", alias="evidenceText")
    source: str = ""


def unknown_registry_namespace() -> RegistryNamespace:
    return RegistryNamespace(
        namespace="",
        server="",
        type="unknown",
        authority="",
        displayName="",
        verificationStatus="unknown",
    )


class RegistryLatestVersionSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    version: str
    status: RegistryVersionStatus
    quality_score: int | None = Field(default=None, alias="qualityScore")
    trust_report: RegistryTrustReport | None = Field(default=None, alias="trustReport")
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


class RegistryTrustReportComponent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    key: str
    label: str
    score: int | None = None
    status: Literal["passed", "warning", "failed", "unknown"]
    summary: str
    evidence: list[str] = Field(default_factory=list)


class RegistryTrustReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    overall_score: int | None = Field(default=None, alias="overallScore")
    score_source: Literal["manual", "calculated", "pending"] = Field(alias="scoreSource")
    status: Literal["passed", "warning", "failed", "unknown"]
    summary: str
    components: list[RegistryTrustReportComponent] = Field(default_factory=list)


class RegistryServerRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    name: str
    title: str
    description: str
    documentation: str = ""
    registry_namespace: RegistryNamespace = Field(
        default_factory=unknown_registry_namespace,
        alias="registryNamespace",
    )
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
    quality_score: int | None = Field(default=None, alias="qualityScore")
    trust_report: RegistryTrustReport | None = Field(default=None, alias="trustReport")
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
    registry_namespace: RegistryNamespace = Field(
        default_factory=unknown_registry_namespace,
        alias="registryNamespace",
    )
    website_url: str = Field(alias="websiteUrl")
    repository: dict[str, Any] | None = None
    packages: list[dict[str, Any]] = Field(default_factory=list)
    remotes: list[dict[str, Any]] = Field(default_factory=list)
    icons: list[dict[str, Any]] = Field(default_factory=list)
    server_json: dict[str, Any] = Field(alias="serverJson")
    quality_score: int | None = Field(default=None, alias="qualityScore")
    trust_report: RegistryTrustReport | None = Field(default=None, alias="trustReport")
    status: RegistryVersionStatus
    status_message: str = Field(alias="statusMessage")
    is_latest: bool = Field(alias="isLatest")
    owner: ActorSummary | None = None
    organization: ActorSummary | None = None
    created_by: ActorSummary | None = Field(default=None, alias="createdBy")
    updated_by: ActorSummary | None = Field(default=None, alias="updatedBy")
    published_by: ActorSummary | None = Field(default=None, alias="publishedBy")
    approver: ActorSummary | None = None
    partner_support: list[PartnerSupportSummary] = Field(
        default_factory=list,
        alias="partnerSupport",
    )
    published_at: datetime = Field(alias="publishedAt")
    status_changed_at: datetime = Field(alias="statusChangedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class RegistryPublishedServerVersionRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    version: str
    quality_score: int | None = Field(default=None, alias="qualityScore")
    trust_report: RegistryTrustReport | None = Field(default=None, alias="trustReport")
    packages: list[dict[str, Any]] = Field(default_factory=list)
    remotes: list[dict[str, Any]] = Field(default_factory=list)
    status: RegistryVersionStatus
    status_message: str = Field(alias="statusMessage")
    is_latest: bool = Field(alias="isLatest")
    published_at: datetime = Field(alias="publishedAt")
    status_changed_at: datetime = Field(alias="statusChangedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class RegistryListMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    count: int
    next_cursor: str = Field(default="", alias="nextCursor")


class RegistryPageMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page: int
    per_page: int = Field(alias="perPage")
    total: int
    pages: int


class RegistryServerListResponse(BaseModel):
    servers: list[RegistryServerRead]
    metadata: RegistryListMetadata


class RegistryCatalogServerRead(RegistryServerRead):
    versions: list[RegistryPublishedServerVersionRead]


class RegistryPublishedServerListResponse(BaseModel):
    servers: list[RegistryCatalogServerRead]
    metadata: RegistryPageMetadata


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


class RegistryServerTabServerRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    name: str
    title: str
    icons: list[dict[str, Any]] = Field(default_factory=list)


class RegistryServerSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    name: str
    title: str
    description: str
    icons: list[dict[str, Any]] = Field(default_factory=list)


class RegistryServerOverviewServerRead(RegistryServerTabServerRead):
    description: str
    registry_namespace: RegistryNamespace = Field(
        default_factory=unknown_registry_namespace,
        alias="registryNamespace",
    )
    website_url: str = Field(alias="websiteUrl")
    repository: dict[str, Any] | None = None
    categories: list[RegistryCategoryRead] = Field(default_factory=list)
    updated_at: datetime = Field(alias="updatedAt")


class RegistryServerOverviewVersionRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    version: str
    title: str
    description: str
    documentation: str = ""
    website_url: str = Field(alias="websiteUrl")
    repository: dict[str, Any] | None = None
    registry_namespace: RegistryNamespace = Field(
        default_factory=unknown_registry_namespace,
        alias="registryNamespace",
    )
    packages: list[dict[str, Any]] = Field(default_factory=list)
    remotes: list[dict[str, Any]] = Field(default_factory=list)
    server_json: dict[str, Any] = Field(default_factory=dict, alias="serverJson")
    quality_score: int | None = Field(default=None, alias="qualityScore")
    trust_report: RegistryTrustReport | None = Field(default=None, alias="trustReport")
    is_latest: bool = Field(alias="isLatest")
    partner_support: list[PartnerSupportSummary] = Field(
        default_factory=list,
        alias="partnerSupport",
    )
    published_at: datetime = Field(alias="publishedAt")
    updated_at: datetime = Field(alias="updatedAt")
    published_by: ActorSummary | None = Field(default=None, alias="publishedBy")


class RegistryToolParameterRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    type_: str = Field(default="", alias="type")
    description: str = ""
    required: bool = False
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")


class RegistryToolRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    title: str = ""
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict, alias="inputSchema")
    output_schema: dict[str, Any] = Field(default_factory=dict, alias="outputSchema")
    annotations: dict[str, Any] = Field(default_factory=dict)
    icons: list[dict[str, Any]] = Field(default_factory=list)
    execution: dict[str, Any] = Field(default_factory=dict)
    parameters: list[RegistryToolParameterRead] = Field(default_factory=list)


class RegistryPromptArgumentRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str = ""
    required: bool = False


class RegistryPromptRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    title: str = ""
    description: str = ""
    arguments: list[RegistryPromptArgumentRead] = Field(default_factory=list)
    icons: list[dict[str, Any]] = Field(default_factory=list)


class RegistryResourceRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    uri: str
    name: str = ""
    title: str = ""
    description: str = ""
    mime_type: str = Field(default="", alias="mimeType")
    size: int | None = None
    annotations: dict[str, Any] = Field(default_factory=dict)
    icons: list[dict[str, Any]] = Field(default_factory=list)


class RegistryResourceTemplateRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    uri_template: str = Field(alias="uriTemplate")
    name: str = ""
    title: str = ""
    description: str = ""
    mime_type: str = Field(default="", alias="mimeType")
    annotations: dict[str, Any] = Field(default_factory=dict)
    icons: list[dict[str, Any]] = Field(default_factory=list)


class RegistryServerSchemaVersionRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    version: str
    title: str
    is_latest: bool = Field(alias="isLatest")
    packages: list[dict[str, Any]] = Field(default_factory=list)
    remotes: list[dict[str, Any]] = Field(default_factory=list)
    server_json: dict[str, Any] = Field(default_factory=dict, alias="serverJson")
    tools: list[RegistryToolRead] = Field(default_factory=list)


class RegistryServerToolsVersionRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    version: str
    title: str
    is_latest: bool = Field(alias="isLatest")
    tools: list[RegistryToolRead] = Field(default_factory=list)


class RegistryServerPromptsVersionRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    version: str
    title: str
    is_latest: bool = Field(alias="isLatest")
    prompts: list[RegistryPromptRead] = Field(default_factory=list)


class RegistryServerResourcesVersionRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    version: str
    title: str
    is_latest: bool = Field(alias="isLatest")
    resources: list[RegistryResourceRead] = Field(default_factory=list)
    resource_templates: list[RegistryResourceTemplateRead] = Field(
        default_factory=list,
        alias="resourceTemplates",
    )


class RegistryServerScoreVersionRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    version: str
    title: str
    is_latest: bool = Field(alias="isLatest")
    quality_score: int | None = Field(default=None, alias="qualityScore")
    trust_report: RegistryTrustReport | None = Field(default=None, alias="trustReport")


class RegistryServerOverviewTabResponse(BaseModel):
    server: RegistryServerOverviewServerRead
    versions: list[RegistryServerOverviewVersionRead] = Field(default_factory=list)
    partner_support: list[PartnerSupportSummary] = Field(
        default_factory=list,
        alias="partnerSupport",
    )


class RegistryServerSchemaTabResponse(BaseModel):
    server: RegistryServerTabServerRead
    versions: list[RegistryServerSchemaVersionRead] = Field(default_factory=list)


class RegistryServerToolsTabResponse(BaseModel):
    server: RegistryServerTabServerRead
    versions: list[RegistryServerToolsVersionRead] = Field(default_factory=list)


class RegistryServerPromptsTabResponse(BaseModel):
    server: RegistryServerTabServerRead
    versions: list[RegistryServerPromptsVersionRead] = Field(default_factory=list)


class RegistryServerResourcesTabResponse(BaseModel):
    server: RegistryServerTabServerRead
    versions: list[RegistryServerResourcesVersionRead] = Field(default_factory=list)


class RegistryServerScoreTabResponse(BaseModel):
    server: RegistryServerTabServerRead
    versions: list[RegistryServerScoreVersionRead] = Field(default_factory=list)


class RegistryOwnershipClaimResponse(RegistryServerDetailResponse):
    verified: bool = True
    verification_source: str = Field(alias="verificationSource")


class RegistryServerVersionDetailResponse(BaseModel):
    server: RegistryServerRead
    version: RegistryServerVersionRead
    support: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None


class RegistryQualityScoreUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    quality_score: int = Field(alias="qualityScore", ge=0, le=100)
    trust_report: RegistryTrustReport | None = Field(default=None, alias="trustReport")
