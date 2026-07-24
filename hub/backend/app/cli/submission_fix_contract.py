from __future__ import annotations

import copy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def merge_mapping(current: Any, repaired: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(current) if isinstance(current, dict) else {}
    merged.update(repaired)
    return merged


def matching_list_item(
    current: Any,
    *,
    index: int,
    identity_key: str,
    identity_value: str,
) -> dict[str, Any]:
    if not isinstance(current, list):
        return {}
    if identity_value:
        for item in current:
            if (
                isinstance(item, dict)
                and str(item.get(identity_key) or "") == identity_value
            ):
                return item
    if index < len(current) and isinstance(current[index], dict):
        return current[index]
    return {}


class StrictOutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SubmissionFixKeyValue(StrictOutputModel):
    name: str
    value: str


class SubmissionFixRepository(StrictOutputModel):
    source: str
    type_: str = Field(alias="type")
    url: str
    subfolder: str
    branch: str
    tag: str


class SubmissionFixIcon(StrictOutputModel):
    src: str
    type_: str = Field(alias="type")
    sizes: str | list[str]


class SubmissionFixTransport(StrictOutputModel):
    type_: str = Field(alias="type")
    command: str
    args: list[str]
    env: list[SubmissionFixKeyValue]

    def to_registry_json(self, current: Any = None) -> dict[str, Any]:
        data = self.model_dump(mode="json", by_alias=True)
        data["env"] = {entry.name: entry.value for entry in self.env}
        return merge_mapping(current, data)


class SubmissionFixEnvironmentVariable(StrictOutputModel):
    name: str
    description: str
    value: str
    default: str
    format: str
    is_required: bool | None = Field(alias="isRequired")
    is_secret: bool | None = Field(alias="isSecret")


class SubmissionFixPackageArgument(StrictOutputModel):
    name: str
    flag: str
    value: str
    default: str
    description: str
    format: str
    requires_value: bool = Field(alias="requiresValue")
    include_in_launch: bool = Field(alias="includeInLaunch")
    options: list[str]
    allowed_values: list[str] = Field(alias="allowedValues")
    is_required: bool | None = Field(alias="isRequired")
    is_secret: bool | None = Field(alias="isSecret")


class SubmissionFixPackage(StrictOutputModel):
    registry_type: str = Field(alias="registryType")
    registry_base_url: str = Field(alias="registryBaseUrl")
    identifier: str
    version: str
    runtime_hint: str = Field(alias="runtimeHint")
    transport: SubmissionFixTransport | None
    environment_variables: list[SubmissionFixEnvironmentVariable] = Field(
        alias="environmentVariables"
    )
    package_arguments: list[SubmissionFixPackageArgument] = Field(alias="packageArguments")

    def to_registry_json(self, current: Any = None) -> dict[str, Any]:
        data = self.model_dump(mode="json", by_alias=True)
        if self.transport is not None:
            current_transport = current.get("transport") if isinstance(current, dict) else None
            data["transport"] = self.transport.to_registry_json(current_transport)
        return merge_mapping(current, data)


class SubmissionFixRemoteHeader(StrictOutputModel):
    name: str
    value: str
    description: str
    is_required: bool = Field(alias="isRequired")
    is_secret: bool = Field(alias="isSecret")


class SubmissionFixRemoteQueryParameter(StrictOutputModel):
    name: str
    value: str
    description: str
    is_required: bool = Field(alias="isRequired")
    is_secret: bool = Field(alias="isSecret")


class SubmissionFixRemoteAuthentication(StrictOutputModel):
    type_: str = Field(alias="type")


class SubmissionFixRemote(StrictOutputModel):
    type_: str = Field(alias="type")
    url: str
    headers: list[SubmissionFixRemoteHeader]
    query_parameters: list[SubmissionFixRemoteQueryParameter] = Field(alias="queryParameters")
    authentication: SubmissionFixRemoteAuthentication | None

    def to_registry_json(self, current: Any = None) -> dict[str, Any]:
        data = self.model_dump(mode="json", by_alias=True)
        if self.authentication is None:
            data["authentication"] = {}
        else:
            current_authentication = (
                current.get("authentication") if isinstance(current, dict) else None
            )
            data["authentication"] = merge_mapping(
                current_authentication,
                self.authentication.model_dump(mode="json", by_alias=True),
            )
        return merge_mapping(current, data)


class SubmissionFixRegistryNamespace(StrictOutputModel):
    namespace: str
    type_: Literal["github", "domain", "unknown"] = Field(alias="type")
    authority: str
    verification_status: Literal[
        "verified",
        "unverified",
        "imported",
        "conflict",
        "unknown",
    ] = Field(alias="verificationStatus")
    verification_method: str = Field(alias="verificationMethod")
    evidence_url: str = Field(alias="evidenceUrl")
    source: str


class SubmissionFixSourceReview(StrictOutputModel):
    files_read: list[str] = Field(alias="filesRead")
    install_commands: list[str] = Field(alias="installCommands")
    command_arguments: list[str | SubmissionFixPackageArgument] = Field(
        alias="commandArguments"
    )
    environment_variables: list[SubmissionFixEnvironmentVariable] = Field(
        alias="environmentVariables"
    )
    prerequisites: list[str]
    capabilities_reviewed: bool = Field(alias="capabilitiesReviewed")
    limitations_reviewed: bool = Field(alias="limitationsReviewed")
    unknowns: list[str]


class SubmissionFixSourceReviewChannels(StrictOutputModel):
    llm: SubmissionFixSourceReview


class SubmissionFixMetadata(StrictOutputModel):
    categories: list[str] = Field(min_length=1)
    registry_namespace: SubmissionFixRegistryNamespace | None = Field(
        alias="registryNamespace"
    )
    source_review: SubmissionFixSourceReviewChannels = Field(alias="sourceReview")


class SubmissionFixServerJson(StrictOutputModel):
    schema_uri: str = Field(alias="$schema")
    name: str
    description: str
    documentation: str
    title: str
    repository: SubmissionFixRepository | None
    version: str
    website_url: str = Field(alias="websiteUrl")
    icons: list[SubmissionFixIcon]
    packages: list[SubmissionFixPackage]
    remotes: list[SubmissionFixRemote]
    meta: SubmissionFixMetadata = Field(alias="_meta")

    @model_validator(mode="after")
    def require_package_or_remote(self) -> SubmissionFixServerJson:
        if not self.packages and not self.remotes:
            raise ValueError("at least one package or remote target is required")
        return self

    def to_registry_json(self, current_server_json: dict[str, Any]) -> dict[str, Any]:
        current = copy.deepcopy(current_server_json)
        data = self.model_dump(mode="json", by_alias=True)

        current_repository = current.get("repository")
        if self.repository is not None:
            data["repository"] = merge_mapping(
                current_repository,
                self.repository.model_dump(mode="json", by_alias=True),
            )

        current_icons = current.get("icons")
        data["icons"] = [
            merge_mapping(
                matching_list_item(
                    current_icons,
                    index=index,
                    identity_key="src",
                    identity_value=icon.src,
                ),
                icon.model_dump(mode="json", by_alias=True),
            )
            for index, icon in enumerate(self.icons)
        ]

        current_packages = current.get("packages")
        data["packages"] = [
            package.to_registry_json(
                matching_list_item(
                    current_packages,
                    index=index,
                    identity_key="identifier",
                    identity_value=package.identifier,
                )
            )
            for index, package in enumerate(self.packages)
        ]

        current_remotes = current.get("remotes")
        data["remotes"] = [
            remote.to_registry_json(
                matching_list_item(
                    current_remotes,
                    index=index,
                    identity_key="url",
                    identity_value=remote.url,
                )
            )
            for index, remote in enumerate(self.remotes)
        ]

        repair_meta = data.pop("_meta")
        current_meta = current.get("_meta")
        merged_meta = copy.deepcopy(current_meta) if isinstance(current_meta, dict) else {}
        merged_meta["categories"] = repair_meta["categories"]

        registry_namespace = repair_meta["registryNamespace"]
        if registry_namespace is None:
            merged_meta.pop("registryNamespace", None)
        else:
            merged_meta["registryNamespace"] = registry_namespace

        current_source_review = merged_meta.get("sourceReview")
        merged_source_review = (
            copy.deepcopy(current_source_review)
            if isinstance(current_source_review, dict)
            else {}
        )
        merged_source_review["llm"] = repair_meta["sourceReview"]["llm"]
        merged_meta["sourceReview"] = merged_source_review
        data["_meta"] = merged_meta

        current.update(data)
        return current
