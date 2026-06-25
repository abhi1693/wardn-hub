from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.registry.schemas import (
    RegistryIcon,
    RegistryPackage,
    RegistryRemote,
    RegistryRepository,
)

DEFAULT_SERVER_SCHEMA = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"


class ServerSourceImportRequest(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "repositoryUrl": "https://github.com/acme/weather-mcp",
                    "subfolder": "",
                },
                {
                    "repositoryUrl": "acme/monorepo",
                    "subfolder": "packages/weather-mcp",
                },
            ]
        },
    )

    repository_url: str = Field(
        alias="repositoryUrl",
        min_length=1,
        max_length=500,
        description="GitHub repository URL, SSH URL, or owner/repo shorthand to import.",
        examples=["https://github.com/acme/weather-mcp"],
    )
    subfolder: str = Field(
        default="",
        max_length=500,
        description="Optional repository subfolder that contains the MCP server metadata.",
        examples=["packages/weather-mcp"],
    )


class ServerSourceImportServerJson(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "$schema": DEFAULT_SERVER_SCHEMA,
                    "name": "io.github.acme/weather-mcp",
                    "title": "Weather MCP",
                    "description": "Weather forecast tools for MCP clients.",
                    "documentation": (
                        "# Weather MCP\n\nWeather forecast tools.\n\n"
                        "## Configuration\nSet WEATHER_API_TOKEN before starting the server."
                    ),
                    "repository": {
                        "source": "github",
                        "url": "acme/weather-mcp",
                    },
                    "version": "1.0.0",
                    "websiteUrl": "https://github.com/acme/weather-mcp#readme",
                    "icons": [{"src": "https://github.com/acme.png"}],
                    "packages": [
                        {
                            "registryType": "npm",
                            "identifier": "@acme/weather-mcp",
                            "transport": {"type": "stdio"},
                        }
                    ],
                    "remotes": [],
                }
            ]
        },
    )

    schema_uri: str = Field(default=DEFAULT_SERVER_SCHEMA, alias="$schema")
    name: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=100)
    description: str = ""
    documentation: str = ""
    repository: RegistryRepository | None = None
    version: str = Field(default="1.0.0", max_length=255)
    website_url: str = Field(default="", alias="websiteUrl", max_length=2048)
    icons: list[RegistryIcon] = Field(default_factory=list)
    packages: list[RegistryPackage] = Field(default_factory=list)
    remotes: list[RegistryRemote] = Field(default_factory=list)
    meta: dict[str, object] | None = Field(default=None, alias="_meta")


class ServerSourceImportSubmissionPayload(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "submissionType": "new_server",
                    "ownerUserId": None,
                    "ownerOrganizationId": None,
                    "serverJson": {
                        "$schema": DEFAULT_SERVER_SCHEMA,
                        "name": "io.github.acme/weather-mcp",
                        "title": "Weather MCP",
                        "description": "Weather forecast tools for MCP clients.",
                        "version": "1.0.0",
                        "packages": [
                            {
                                "registryType": "npm",
                                "identifier": "@acme/weather-mcp",
                                "transport": {"type": "stdio"},
                            }
                        ],
                        "remotes": [],
                    },
                }
            ]
        },
    )

    submission_type: Literal[
        "new_server",
        "new_version",
        "metadata_edit",
        "takedown_appeal",
    ] = Field(default="new_server", alias="submissionType")
    owner_user_id: UUID | None = Field(default=None, alias="ownerUserId")
    owner_organization_id: UUID | None = Field(default=None, alias="ownerOrganizationId")
    server_json: ServerSourceImportServerJson = Field(alias="serverJson")


class ServerSourceImportEvidence(BaseModel):
    files: list[str] = Field(
        default_factory=list,
        description="Repository files used to build the import draft.",
        examples=[["README.md", "server.json"]],
    )
    missing: list[str] = Field(
        default_factory=list,
        description="Required or important fields that could not be inferred.",
        examples=[["packages or remotes"]],
    )


class ServerSourceImportResponse(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "source": "server.json",
                    "name": "io.github.acme/weather-mcp",
                    "title": "Weather MCP",
                    "description": "Weather forecast tools for MCP clients.",
                    "documentation": "# Weather MCP\n\nWeather forecast tools.",
                    "version": "1.0.0",
                    "websiteUrl": "https://github.com/acme/weather-mcp#readme",
                    "repository": {
                        "source": "github",
                        "url": "acme/weather-mcp",
                    },
                    "iconUrl": "https://github.com/acme.png",
                    "icons": [{"src": "https://github.com/acme.png"}],
                    "packages": [
                        {
                            "registryType": "npm",
                            "identifier": "@acme/weather-mcp",
                            "transport": {"type": "stdio"},
                        }
                    ],
                    "remotes": [],
                    "serverJson": {
                        "$schema": DEFAULT_SERVER_SCHEMA,
                        "name": "io.github.acme/weather-mcp",
                        "title": "Weather MCP",
                        "description": "Weather forecast tools for MCP clients.",
                        "version": "1.0.0",
                        "packages": [
                            {
                                "registryType": "npm",
                                "identifier": "@acme/weather-mcp",
                                "transport": {"type": "stdio"},
                            }
                        ],
                        "remotes": [],
                    },
                    "submissionPayload": {
                        "submissionType": "new_server",
                        "serverJson": {
                            "$schema": DEFAULT_SERVER_SCHEMA,
                            "name": "io.github.acme/weather-mcp",
                            "description": "Weather forecast tools for MCP clients.",
                            "version": "1.0.0",
                            "packages": [
                                {
                                    "registryType": "npm",
                                    "identifier": "@acme/weather-mcp",
                                    "transport": {"type": "stdio"},
                                }
                            ],
                            "remotes": [],
                        },
                    },
                    "evidence": {"files": ["README.md", "server.json"], "missing": []},
                }
            ]
        },
    )

    source: Literal["github", "server.json", "mcp.json"]
    name: str = ""
    title: str = ""
    description: str = ""
    documentation: str = ""
    version: str = ""
    website_url: str = Field(default="", alias="websiteUrl")
    repository: RegistryRepository | None = None
    icon_url: str = Field(default="", alias="iconUrl")
    icons: list[RegistryIcon] = Field(default_factory=list)
    remotes: list[RegistryRemote] = Field(default_factory=list)
    packages: list[RegistryPackage] = Field(default_factory=list)
    server_json: ServerSourceImportServerJson = Field(
        default_factory=ServerSourceImportServerJson,
        alias="serverJson",
    )
    submission_payload: ServerSourceImportSubmissionPayload = Field(alias="submissionPayload")
    evidence: ServerSourceImportEvidence = Field(default_factory=ServerSourceImportEvidence)
