from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SkillSourceType = Literal["github", "well-known"]
SkillStatus = Literal["active", "deprecated", "deleted", "quarantined"]
SkillVisibility = Literal["public", "unlisted", "private_preview"]
SkillAuditStatus = Literal["pass", "warn", "fail"]


class SkillRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    slug: str
    name: str
    source: str
    source_type: str = Field(alias="sourceType")
    source_owner: str = Field(default="", alias="sourceOwner")
    source_name: str = Field(default="", alias="sourceName")
    source_owner_url: str | None = Field(default=None, alias="sourceOwnerUrl")
    source_owner_icon_url: str | None = Field(default=None, alias="sourceOwnerIconUrl")
    source_url: str | None = Field(default=None, alias="sourceUrl")
    install_url: str | None = Field(default=None, alias="installUrl")
    url: str
    description: str = ""
    is_official: bool = Field(default=False, alias="isOfficial")
    is_duplicate: bool | None = Field(default=None, alias="isDuplicate")


class SkillPagination(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page: int
    per_page: int = Field(alias="perPage")
    total: int
    has_more: bool = Field(alias="hasMore")


class SkillListResponse(BaseModel):
    data: list[SkillRead]
    pagination: SkillPagination


class SkillSearchResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: list[SkillRead]
    query: str
    search_type: str = Field(alias="searchType")
    count: int
    duration_ms: int = Field(alias="durationMs")


class SkillFileRead(BaseModel):
    path: str
    contents: str


class SkillDetailResponse(BaseModel):
    id: str
    source: str
    slug: str
    source_owner: str = Field(default="", alias="sourceOwner")
    source_name: str = Field(default="", alias="sourceName")
    source_owner_url: str | None = Field(default=None, alias="sourceOwnerUrl")
    source_owner_icon_url: str | None = Field(default=None, alias="sourceOwnerIconUrl")
    source_url: str | None = Field(default=None, alias="sourceUrl")
    hash: str | None = None
    files: list[SkillFileRead] | None = None


class SkillAuditRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: str
    slug: str
    status: str
    summary: str
    audited_at: datetime = Field(alias="auditedAt")
    risk_level: str | None = Field(default=None, alias="riskLevel")
    categories: list[str] | None = None


class SkillAuditResponse(BaseModel):
    id: str
    source: str
    slug: str
    audits: list[SkillAuditRead]


class OfficialSkillOwner(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    owner: str
    source_owner_icon_url: str | None = Field(default=None, alias="sourceOwnerIconUrl")
    owner_url: str | None = Field(default=None, alias="ownerUrl")
    featured_repo: str = Field(alias="featuredRepo")
    featured_skill: str = Field(alias="featuredSkill")
    skills: list[SkillRead]


class SkillOfficialResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: list[OfficialSkillOwner]
    total_owners: int = Field(alias="totalOwners")
    total_skills: int = Field(alias="totalSkills")
    generated_at: datetime = Field(alias="generatedAt")


class SkillSnapshotCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_type: SkillSourceType = Field(default="github", alias="sourceType")
    source: str
    source_owner: str = Field(default="", alias="sourceOwner")
    source_name: str = Field(default="", alias="sourceName")
    source_owner_url: str = Field(default="", alias="sourceOwnerUrl")
    source_owner_icon_url: str = Field(default="", alias="sourceOwnerIconUrl")
    source_url: str = Field(default="", alias="sourceUrl")
    slug: str
    name: str
    description: str = ""
    install_url: str = Field(default="", alias="installUrl")
    website_url: str = Field(default="", alias="websiteUrl")
    repository: dict[str, Any] | None = None
    content_hash: str | None = Field(default=None, alias="contentHash")
    skill_md: str = Field(default="", alias="skillMd")
    metadata: dict[str, Any] = Field(default_factory=dict)
    files: list[SkillFileRead] = Field(default_factory=list)
