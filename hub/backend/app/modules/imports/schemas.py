from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ServerSourceImportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    repository_url: str = Field(alias="repositoryUrl", min_length=1, max_length=500)
    subfolder: str = Field(default="", max_length=500)


class ServerSourceImportEvidence(BaseModel):
    files: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class ServerSourceImportResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: str
    name: str = ""
    title: str = ""
    description: str = ""
    documentation: str = ""
    version: str = ""
    website_url: str = Field(default="", alias="websiteUrl")
    repository: dict[str, Any] = Field(default_factory=dict)
    icon_url: str = Field(default="", alias="iconUrl")
    icons: list[dict[str, Any]] = Field(default_factory=list)
    remotes: list[dict[str, Any]] = Field(default_factory=list)
    packages: list[dict[str, Any]] = Field(default_factory=list)
    server_json: dict[str, Any] = Field(default_factory=dict, alias="serverJson")
    submission_payload: dict[str, Any] = Field(default_factory=dict, alias="submissionPayload")
    evidence: ServerSourceImportEvidence = Field(default_factory=ServerSourceImportEvidence)
