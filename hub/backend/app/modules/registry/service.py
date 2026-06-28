import asyncio
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel

from app.modules.events.service import emit_event_record, subject_payload
from app.modules.registry import repository
from app.modules.registry.category_seed import MCP_SERVERS_CATEGORY_SEEDS
from app.modules.registry.exceptions import (
    DuplicateRegistryCategoryError,
    DuplicateRegistryVersionError,
    InvalidRegistryCursorError,
    RegistryCategoryNotFoundError,
    RegistryOwnershipClaimConflictError,
    RegistryOwnershipClaimError,
    RegistryServerNotFoundError,
    RegistryVersionNotFoundError,
)
from app.modules.registry.models import RegistryCategory, RegistryServer, RegistryServerVersion
from app.modules.registry.schemas import (
    ActorSummary,
    MCPServerDocument,
    PartnerSupportSummary,
    RegistryCatalogServerRead,
    RegistryCategoryCreate,
    RegistryCategoryListResponse,
    RegistryCategoryRead,
    RegistryCategoryUpdate,
    RegistryLatestVersionSummary,
    RegistryListMetadata,
    RegistryOwnershipClaimResponse,
    RegistryPageMetadata,
    RegistryPublishedServerListResponse,
    RegistryPublishedServerVersionRead,
    RegistryServerDetailResponse,
    RegistryServerListResponse,
    RegistryServerRead,
    RegistryServerVersionCreate,
    RegistryServerVersionDetailResponse,
    RegistryServerVersionListResponse,
    RegistryServerVersionRead,
    RegistryServerVersionUpdate,
    RegistryTrustReport,
    RegistryTrustReportComponent,
    RegistryUserDetailResponse,
    RegistryUserListResponse,
    RegistryUserRead,
    normalize_remote_mapping,
)
from app.modules.users.exceptions import UserNotFoundError


@dataclass
class RegistryTrustContext:
    users: dict[UUID, object]
    organizations: dict[UUID, object]
    partner_support: dict[str, list[tuple[object, object]]]
    categories: dict[UUID, list[RegistryCategory]]


@dataclass(frozen=True)
class WardnOwnershipRepository:
    owner: str
    repo: str
    branch: str = ""
    tag: str = ""


@dataclass(frozen=True)
class WardnOwnershipManifest:
    payload: dict[str, Any]
    source_url: str


EMPTY_TRUST_CONTEXT = RegistryTrustContext(
    users={},
    organizations={},
    partner_support={},
    categories={},
)
METADATA_FIELD = "metadata"


def project_list_response_fields(
    response: RegistryServerListResponse | RegistryPublishedServerListResponse,
    *,
    fields: str | None,
) -> dict | None:
    requested_fields = parse_response_fields(fields)
    if requested_fields is None:
        return None

    allowed_fields = server_response_fields(response)
    unknown_fields = requested_fields - allowed_fields - {METADATA_FIELD}
    if unknown_fields:
        unknown = ", ".join(sorted(unknown_fields))
        raise ValueError(f"unknown response field(s): {unknown}")

    item_fields = requested_fields - {METADATA_FIELD}
    return {
        "servers": [
            project_model_fields(server, item_fields)
            for server in response.servers
        ],
        "metadata": response.metadata.model_dump(by_alias=True),
    }


def parse_response_fields(fields: str | None) -> set[str] | None:
    if fields is None:
        return None

    parsed_fields = {field.strip() for field in fields.split(",") if field.strip()}
    if not parsed_fields:
        raise ValueError("fields must include at least one response field")
    return parsed_fields


def server_response_fields(
    response: RegistryServerListResponse | RegistryPublishedServerListResponse,
) -> set[str]:
    if response.servers:
        return set(response.servers[0].model_dump(by_alias=True))
    model = (
        RegistryCatalogServerRead
        if isinstance(response, RegistryPublishedServerListResponse)
        else RegistryServerRead
    )
    return {
        field.alias or field_name
        for field_name, field in model.model_fields.items()
    }


def project_model_fields(model: BaseModel, fields: set[str]) -> dict:
    payload = model.model_dump(by_alias=True)
    return {field: payload[field] for field in fields if field in payload}


PUBLISHER_META_KEY = "io.modelcontextprotocol.registry/publisher-provided"
PRIVATE_METADATA_KEYS = {
    "evidence",
    "filesread",
    "importevidence",
    "packageversionevidence",
    "reviewnotes",
    "source",
    "sourcereview",
    "sources",
    "staleversionreferences",
    "staleversionreferencesreviewed",
    "wardnownership",
    "wardntrustreport",
}
WARDN_OWNERSHIP_FILE = "wardn.json"
WARDN_OWNERSHIP_META_KEY = "wardnOwnership"
WARDN_OWNERSHIP_SCHEMA_URL = "https://wardn.ai/schemas/wardn.json"
WARDN_OWNERSHIP_MAX_REDIRECTS = 5


def parse_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise InvalidRegistryCursorError("invalid registry cursor") from exc
    if offset < 0:
        raise InvalidRegistryCursorError("invalid registry cursor")
    return offset


def registry_json(value):
    if isinstance(value, BaseModel):
        return registry_json(value.model_dump(by_alias=True))
    if isinstance(value, list):
        return [registry_json(item) for item in value]
    if isinstance(value, dict):
        return {key: registry_json(item) for key, item in value.items()}
    return value


def registry_remotes_json(value):
    if isinstance(value, BaseModel):
        return registry_json(value)
    if isinstance(value, list):
        return [registry_json(normalize_remote_mapping(item)) for item in value]
    return registry_json(value)


def normalized_metadata_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def public_registry_json(value, *, parent_key: str = ""):
    if isinstance(value, BaseModel):
        return public_registry_json(value.model_dump(by_alias=True), parent_key=parent_key)
    if isinstance(value, list):
        return [public_registry_json(item, parent_key=parent_key) for item in value]
    if not isinstance(value, dict):
        return value

    public_value = {}
    for key, item in value.items():
        normalized_key = normalized_metadata_key(str(key))
        normalized_parent = normalized_metadata_key(parent_key)
        if normalized_key in PRIVATE_METADATA_KEYS and normalized_parent != "repository":
            continue
        public_value[key] = public_registry_json(item, parent_key=str(key))
    return public_value


def github_repository_from_registry_repository(
    repository_payload: dict[str, Any] | None,
) -> WardnOwnershipRepository | None:
    repository_value = registry_record(repository_payload)
    source = str(repository_value.get("source") or "").lower()
    url = str(repository_value.get("url") or "").strip().removesuffix(".git")
    if not url:
        return None

    match = re.match(r"^(?:https?://github\.com/)?([^/\s]+)/([^/\s#?]+)$", url)
    if not match and source == "github":
        match = re.match(r"^([^/\s]+)/([^/\s#?]+)$", url)
    if not match:
        return None
    return WardnOwnershipRepository(
        owner=match.group(1),
        repo=match.group(2),
        branch=str(repository_value.get("branch") or ""),
        tag=str(repository_value.get("tag") or ""),
    )


async def fetch_wardn_ownership_manifest(
    repository_ref: WardnOwnershipRepository,
    *,
    timeout: float = 10,
) -> WardnOwnershipManifest:
    refs = [repository_ref.tag, repository_ref.branch]
    metadata_url = f"https://api.github.com/repos/{repository_ref.owner}/{repository_ref.repo}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            metadata_response = await client.get(
                metadata_url,
                headers={"Accept": "application/vnd.github+json"},
            )
            if metadata_response.status_code < 400:
                metadata = metadata_response.json()
                if isinstance(metadata, dict):
                    refs.append(str(metadata.get("default_branch") or ""))
        except (httpx.HTTPError, json.JSONDecodeError):
            pass

        refs.extend(["main", "master"])
        unique_refs = [
            value for index, value in enumerate(refs) if value and value not in refs[:index]
        ]
        for ref in unique_refs:
            source_url = (
                "https://raw.githubusercontent.com/"
                f"{repository_ref.owner}/{repository_ref.repo}/{ref}/{WARDN_OWNERSHIP_FILE}"
            )
            try:
                response = await client.get(source_url, headers={"Accept": "application/json"})
            except httpx.HTTPError:
                continue
            if response.status_code == 404 or response.status_code >= 500:
                continue
            if response.status_code >= 400:
                continue
            try:
                payload = response.json()
            except json.JSONDecodeError:
                raise RegistryOwnershipClaimError("wardn.json is not valid JSON") from None
            if not isinstance(payload, dict):
                raise RegistryOwnershipClaimError("wardn.json must contain a JSON object")
            return WardnOwnershipManifest(payload=payload, source_url=source_url)

    raise RegistryOwnershipClaimError("wardn.json was not found in the linked GitHub repository")


def wardn_ownership_website_url(website_url: str) -> str:
    parsed = urlparse(website_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc, f"/{WARDN_OWNERSHIP_FILE}", "", "", ""))


async def validate_public_ownership_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RegistryOwnershipClaimError("wardn.json website URL must be http or https")
    if parsed.username or parsed.password:
        raise RegistryOwnershipClaimError("wardn.json website URL must not include credentials")

    hostname = parsed.hostname.strip("[]")
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        loop = asyncio.get_running_loop()
        try:
            resolved = await loop.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise RegistryOwnershipClaimError(
                "wardn.json website host could not be resolved"
            ) from exc
        addresses = []
        for item in resolved:
            address = item[4][0]
            try:
                addresses.append(ipaddress.ip_address(address))
            except ValueError:
                continue

    if not addresses or any(not address.is_global for address in addresses):
        raise RegistryOwnershipClaimError(
            "wardn.json website host must resolve to a public address"
        )
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", parsed.query, ""))


async def fetch_wardn_ownership_manifest_from_website(
    website_url: str,
    *,
    timeout: float = 10,
) -> WardnOwnershipManifest:
    source_url = wardn_ownership_website_url(website_url)
    if not source_url:
        raise RegistryOwnershipClaimError("server must provide a website URL to use wardn.json")

    current_url = await validate_public_ownership_url(source_url)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(WARDN_OWNERSHIP_MAX_REDIRECTS + 1):
            try:
                response = await client.get(current_url, headers={"Accept": "application/json"})
            except httpx.HTTPError as exc:
                raise RegistryOwnershipClaimError(
                    "wardn.json was not found at the website root"
                ) from exc
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            redirect_url = response.headers.get("location")
            if not redirect_url:
                break
            current_url = await validate_public_ownership_url(urljoin(current_url, redirect_url))
        else:
            raise RegistryOwnershipClaimError("wardn.json website redirects too many times")

    if response.status_code == 404 or response.status_code >= 500:
        raise RegistryOwnershipClaimError("wardn.json was not found at the website root")
    if response.status_code >= 400:
        raise RegistryOwnershipClaimError("wardn.json could not be read from the website root")
    try:
        payload = response.json()
    except json.JSONDecodeError:
        raise RegistryOwnershipClaimError("wardn.json is not valid JSON") from None
    if not isinstance(payload, dict):
        raise RegistryOwnershipClaimError("wardn.json must contain a JSON object")
    return WardnOwnershipManifest(payload=payload, source_url=str(response.url))


def owner_user_ids_from_manifest(payload: dict[str, Any], server_name: str) -> set[UUID]:
    candidates: list[Any] = [
        payload.get("owners"),
        payload.get("ownerUserIds"),
        registry_record(payload.get("wardn")).get("owners"),
        registry_record(payload.get("wardn")).get("ownerUserIds"),
    ]
    for key in ("servers", "mcpServers"):
        server_map = payload.get(key)
        if isinstance(server_map, dict):
            server_entry = server_map.get(server_name)
            if isinstance(server_entry, dict):
                candidates.extend([server_entry.get("owners"), server_entry.get("ownerUserIds")])
        elif isinstance(server_map, list):
            for item in server_map:
                if isinstance(item, dict) and item.get("name") == server_name:
                    candidates.extend([item.get("owners"), item.get("ownerUserIds")])

    owner_ids: set[UUID] = set()
    for candidate in candidates:
        values = candidate if isinstance(candidate, list) else [candidate]
        for item in values:
            raw_value = item
            if isinstance(item, dict):
                raw_value = item.get("userId") or item.get("userUUID") or item.get("id")
            if not isinstance(raw_value, str):
                continue
            try:
                owner_ids.add(UUID(raw_value.strip()))
            except ValueError:
                continue
    return owner_ids


def attach_wardn_ownership_metadata(
    version: RegistryServerVersion,
    *,
    user_id: UUID,
    source_url: str,
    verified_at: datetime,
) -> None:
    server_json = dict(registry_record(version.server_json))
    meta = dict(registry_record(server_json.get("_meta")))
    meta[WARDN_OWNERSHIP_META_KEY] = {
        "verified": True,
        "method": "wardn.json",
        "userId": str(user_id),
        "source": source_url,
        "verifiedAt": verified_at.isoformat().replace("+00:00", "Z"),
    }
    server_json["_meta"] = meta
    version.server_json = server_json


def document_values(payload: MCPServerDocument) -> dict:
    return {
        "name": payload.name,
        "title": payload.title,
        "description": payload.description,
        "documentation": payload.documentation,
        "version": payload.version,
        "website_url": payload.website_url,
        "repository": registry_json(payload.repository),
        "packages": registry_json(payload.packages),
        "remotes": registry_remotes_json(payload.remotes),
        "icons": registry_json(payload.icons),
        "server_json": payload.model_dump(by_alias=True, exclude_none=True),
    }


def registry_server_event_payload(
    *,
    event_id: UUID,
    event_type: str,
    server: RegistryServer,
    actor_user_id: UUID | None,
    occurred_at: datetime,
) -> dict:
    payload = subject_payload(
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        actor_user_id=actor_user_id,
        actor_token_id=None,
        subject_type="registry_server",
        subject_id=server.id,
        subject={"name": server.name},
        links={"registryServerApiUrl": f"/api/v1/mcp/servers/{server.name}"},
    )
    payload["registryServer"] = {
        "id": str(server.id),
        "name": server.name,
        "title": server.title,
        "status": server.status,
        "visibility": server.visibility,
        "currentVersionId": str(server.current_version_id) if server.current_version_id else None,
    }
    return payload


def registry_version_event_payload(
    *,
    event_id: UUID,
    event_type: str,
    version: RegistryServerVersion,
    actor_user_id: UUID | None,
    occurred_at: datetime,
) -> dict:
    payload = subject_payload(
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        actor_user_id=actor_user_id,
        actor_token_id=None,
        subject_type="registry_server_version",
        subject_id=version.id,
        subject={"name": version.name, "version": version.version},
        links={
            "registryServerApiUrl": f"/api/v1/mcp/servers/{version.name}",
            "registryVersionApiUrl": (
                f"/api/v1/mcp/servers/{version.name}/versions/{version.version}"
            ),
        },
    )
    payload["registryVersion"] = {
        "id": str(version.id),
        "serverId": str(version.server_id),
        "name": version.name,
        "version": version.version,
        "status": version.status,
        "isLatest": version.is_latest,
        "publishedAt": version.published_at.isoformat().replace("+00:00", "Z"),
    }
    return payload


async def emit_registry_server_event(
    session,
    *,
    event_type: str,
    server: RegistryServer,
    actor_user_id: UUID | None,
    occurred_at: datetime | None = None,
) -> None:
    event_id = uuid4()
    occurred_at = occurred_at or datetime.now(UTC)
    await emit_event_record(
        session,
        event_id=event_id,
        event_type=event_type,
        subject_type="registry_server",
        subject_id=server.id,
        actor_user_id=actor_user_id,
        owner_user_id=server.owner_user_id,
        owner_organization_id=server.owner_organization_id,
        payload=registry_server_event_payload(
            event_id=event_id,
            event_type=event_type,
            server=server,
            actor_user_id=actor_user_id,
            occurred_at=occurred_at,
        ),
    )


async def emit_registry_version_event(
    session,
    *,
    event_type: str,
    version: RegistryServerVersion,
    actor_user_id: UUID | None,
    occurred_at: datetime | None = None,
) -> None:
    event_id = uuid4()
    occurred_at = occurred_at or datetime.now(UTC)
    await emit_event_record(
        session,
        event_id=event_id,
        event_type=event_type,
        subject_type="registry_server_version",
        subject_id=version.id,
        actor_user_id=actor_user_id,
        owner_user_id=version.owner_user_id,
        owner_organization_id=version.owner_organization_id,
        payload=registry_version_event_payload(
            event_id=event_id,
            event_type=event_type,
            version=version,
            actor_user_id=actor_user_id,
            occurred_at=occurred_at,
        ),
    )


def category_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "other"


def category_values_from_metadata(metadata: dict) -> list[str]:
    raw_values = []
    for source in (metadata, metadata.get(PUBLISHER_META_KEY, {})):
        if not isinstance(source, dict):
            continue
        category = source.get("category")
        categories = source.get("categories")
        if isinstance(category, str):
            raw_values.append(category)
        if isinstance(categories, list):
            raw_values.extend(value for value in categories if isinstance(value, str))

    slugs = []
    seen = set()
    for value in raw_values:
        slug = category_slug(value)
        if slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    return slugs


def category_values(payload: MCPServerDocument) -> list[str]:
    return category_values_from_metadata(payload.meta or {})


def category_values_from_server_json(server_json: dict) -> list[str]:
    metadata = server_json.get("_meta", {})
    return category_values_from_metadata(metadata if isinstance(metadata, dict) else {})


def registry_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def registry_records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def registry_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def trust_status(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score >= 80:
        return "passed"
    if score >= 50:
        return "warning"
    return "failed"


def trust_component(
    *,
    key: str,
    label: str,
    score: int | None,
    summary: str,
    evidence: list[str] | None = None,
) -> RegistryTrustReportComponent:
    return RegistryTrustReportComponent(
        key=key,
        label=label,
        score=score,
        status=trust_status(score),
        summary=summary,
        evidence=evidence or [],
    )


def percentage_score(passed: int, total: int) -> int | None:
    if total <= 0:
        return None
    return round((passed / total) * 100)


def component_schema_completeness(version: RegistryServerVersion) -> RegistryTrustReportComponent:
    server_json = registry_record(version.server_json)
    packages = registry_records(version.packages)
    remotes = registry_records(version.remotes)
    checks = {
        "Schema URI": bool(server_json.get("$schema")),
        "Registry name": bool(version.name),
        "Semantic version": bool(version.version),
        "Description": bool(version.description.strip()),
        "Package or remote target": bool(packages or remotes),
        "Category": bool(category_values_from_server_json(server_json)),
    }
    missing = [label for label, present in checks.items() if not present]
    score = percentage_score(sum(1 for present in checks.values() if present), len(checks))
    return trust_component(
        key="schemaCompleteness",
        label="Schema completeness",
        score=score,
        summary=(
            "Required registry fields are present."
            if not missing
            else "Required registry fields are incomplete."
        ),
        evidence=(
            ["Missing: " + ", ".join(missing)]
            if missing
            else ["Name, version, category, and target metadata are present."]
        ),
    )


def component_documentation(version: RegistryServerVersion) -> RegistryTrustReportComponent:
    documentation = version.documentation.strip()
    if not documentation:
        return trust_component(
            key="documentation",
            label="Documentation",
            score=0,
            summary="Documentation is empty.",
            evidence=["No documentation was published with this version."],
        )
    lower = documentation.lower()
    sections = {
        "installation": ("installation", "install", "command", "mcpservers"),
        "configuration": ("configuration", "environment", "env", "arguments", "variables"),
        "capabilities": ("capabilities", "tools", "resources", "prompts", "features"),
    }
    present = [
        label
        for label, needles in sections.items()
        if any(needle in lower for needle in needles)
    ]
    missing = [label for label in sections if label not in present]
    score = min(100, 40 + (20 * len(present)))
    return trust_component(
        key="documentation",
        label="Documentation",
        score=score,
        summary=(
            "Documentation covers setup, configuration, and capabilities."
            if not missing
            else "Documentation is present but may be incomplete."
        ),
        evidence=[
            f"Document length: {len(documentation)} characters.",
            *([f"Missing likely sections: {', '.join(missing)}."] if missing else []),
        ],
    )


def source_review_channels(meta: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    source_review = registry_record(meta.get("sourceReview"))
    flat_fields = {
        "filesRead",
        "installCommands",
        "commandArguments",
        "environmentVariables",
        "prerequisites",
        "capabilitiesReviewed",
        "limitationsReviewed",
        "unknowns",
    }
    channels: list[tuple[str, dict[str, Any]]] = []
    if any(field in source_review for field in flat_fields):
        channels.append(("human", source_review))
    for channel in ("human", "llm"):
        channel_review = registry_record(source_review.get(channel))
        if channel_review:
            channels.append((channel, channel_review))
    return channels


def source_review_score(
    review: dict[str, Any],
    *,
    requires_launch_evidence: bool,
) -> tuple[int, list[str]]:
    checks = {
        "files read": bool(registry_strings(review.get("filesRead"))),
        "capabilities reviewed": review.get("capabilitiesReviewed") is True,
        "limitations reviewed": review.get("limitationsReviewed") is True,
        "unknowns resolved": not registry_strings(review.get("unknowns")),
    }
    if requires_launch_evidence:
        install_commands = registry_records(review.get("installCommands")) or registry_strings(
            review.get("installCommands")
        )
        command_arguments = registry_records(review.get("commandArguments")) or registry_strings(
            review.get("commandArguments")
        )
        checks["install commands"] = bool(install_commands)
        checks["command arguments"] = bool(command_arguments)
    missing = [label for label, passed in checks.items() if not passed]
    return (
        percentage_score(sum(1 for passed in checks.values() if passed), len(checks)) or 0,
        missing,
    )


def local_package_targets(packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    local_targets = []
    for package in packages:
        registry_type = str(package.get("registryType") or "").lower()
        if registry_type == "mcpb":
            continue
        transport = registry_record(package.get("transport"))
        transport_type = str(transport.get("type") or "").lower()
        if not transport_type or transport_type in {"stdio", "local"}:
            local_targets.append(package)
    return local_targets


def component_source_review(version: RegistryServerVersion) -> RegistryTrustReportComponent:
    meta = registry_record(registry_record(version.server_json).get("_meta"))
    channels = source_review_channels(meta)
    requires_launch_evidence = bool(local_package_targets(registry_records(version.packages)))
    if not channels:
        return trust_component(
            key="sourceReview",
            label="Source review evidence",
            score=0,
            summary="No source review evidence is published.",
            evidence=[
                "Expected files read, capabilities reviewed, limitations reviewed, "
                "and resolved unknowns."
            ],
        )
    scored = [
        (channel, *source_review_score(review, requires_launch_evidence=requires_launch_evidence))
        for channel, review in channels
    ]
    channel, score, missing = max(scored, key=lambda item: item[1])
    return trust_component(
        key="sourceReview",
        label="Source review evidence",
        score=score,
        summary=f"Best available review channel: {channel}.",
        evidence=(
            [f"Missing from {channel}: {', '.join(missing)}."]
            if missing
            else [f"{channel} review evidence is complete."]
        ),
    )


def component_target_metadata(version: RegistryServerVersion) -> RegistryTrustReportComponent:
    packages = registry_records(version.packages)
    remotes = registry_records(version.remotes)
    checks: dict[str, bool] = {}
    for index, package in enumerate(packages, start=1):
        label = str(package.get("identifier") or f"package {index}")
        transport = registry_record(package.get("transport"))
        checks[f"{label} registry type"] = bool(str(package.get("registryType") or "").strip())
        checks[f"{label} identifier"] = bool(str(package.get("identifier") or "").strip())
        checks[f"{label} transport type"] = bool(str(transport.get("type") or "").strip())
        if package in local_package_targets([package]):
            checks[f"{label} launch command"] = bool(str(transport.get("command") or "").strip())
            checks[f"{label} launch args"] = bool(transport.get("args"))
        env_defaults = registry_record(transport.get("env"))
        if env_defaults:
            documented_env = {
                str(item.get("name") or "").strip()
                for item in registry_records(package.get("environmentVariables"))
                if str(item.get("name") or "").strip()
            }
            checks[f"{label} environment metadata"] = set(env_defaults).issubset(documented_env)
    for index, remote in enumerate(remotes, start=1):
        label = str(remote.get("url") or f"remote {index}")
        checks[f"{label} URL"] = bool(str(remote.get("url") or "").strip())
        checks[f"{label} transport type"] = bool(str(remote.get("type") or "").strip())
    if not checks:
        return trust_component(
            key="targetMetadata",
            label="Package and remote metadata",
            score=0,
            summary="No package or remote target metadata is published.",
            evidence=["At least one package or remote target is required."],
        )
    missing = [label for label, passed in checks.items() if not passed]
    return trust_component(
        key="targetMetadata",
        label="Package and remote metadata",
        score=percentage_score(sum(1 for passed in checks.values() if passed), len(checks)),
        summary=(
            "Package and remote metadata is complete."
            if not missing
            else "Package or remote metadata is incomplete."
        ),
        evidence=(
            ["Missing: " + "; ".join(missing[:6])]
            if missing
            else [f"{len(packages)} package target(s), {len(remotes)} remote target(s)."]
        ),
    )


def component_license(version: RegistryServerVersion) -> RegistryTrustReportComponent:
    server_json = registry_record(version.server_json)
    meta = registry_record(server_json.get("_meta"))
    repository = registry_record(version.repository)
    license_value = (
        server_json.get("license")
        or meta.get("license")
        or registry_record(meta.get("repository")).get("license")
        or repository.get("license")
        or repository.get("licenseSpdxId")
    )
    if isinstance(license_value, dict):
        license_value = license_value.get("spdxId") or license_value.get("name")
    if isinstance(license_value, str) and license_value.strip():
        return trust_component(
            key="license",
            label="License",
            score=100,
            summary="License metadata is published.",
            evidence=[f"License: {license_value.strip()}."],
        )
    return trust_component(
        key="license",
        label="License",
        score=0,
        summary="License metadata is not published.",
        evidence=["Add SPDX license metadata from the repository or package source."],
    )


def parse_trust_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def component_maintenance(version: RegistryServerVersion) -> RegistryTrustReportComponent:
    meta = registry_record(registry_record(version.server_json).get("_meta"))
    maintenance = registry_record(meta.get("maintenance"))
    candidates = [
        maintenance.get("lastCommitAt"),
        maintenance.get("lastReleaseAt"),
        maintenance.get("lastUpdatedAt"),
        registry_record(version.repository).get("updatedAt"),
    ]
    latest = next(
        (parsed for parsed in (parse_trust_datetime(value) for value in candidates) if parsed),
        None,
    )
    if latest is None:
        return trust_component(
            key="maintenance",
            label="Maintenance freshness",
            score=50,
            summary="Maintenance freshness is based only on registry publication dates.",
            evidence=[f"Published on {version.published_at.date().isoformat()}."],
        )
    days_old = max(0, (datetime.now(UTC) - latest).days)
    score = 100 if days_old <= 90 else 80 if days_old <= 180 else 55 if days_old <= 365 else 25
    return trust_component(
        key="maintenance",
        label="Maintenance freshness",
        score=score,
        summary=(
            "Recent upstream maintenance signal is available."
            if score >= 80
            else "Upstream maintenance may be stale."
        ),
        evidence=[f"Latest maintenance signal: {latest.date().isoformat()} ({days_old} days ago)."],
    )


def component_owner_verification(
    version: RegistryServerVersion,
    trust: RegistryTrustContext,
) -> RegistryTrustReportComponent:
    meta = registry_record(registry_record(version.server_json).get("_meta"))
    wardn_ownership = registry_record(meta.get(WARDN_OWNERSHIP_META_KEY))
    if (
        wardn_ownership.get("verified") is True
        and str(wardn_ownership.get("userId") or "") == str(version.owner_user_id)
    ):
        return trust_component(
            key="ownerVerification",
            label="Owner verification",
            score=100,
            summary="Ownership is verified by wardn.json.",
            evidence=[
                "wardn.json lists the Wardn user UUID recorded as this server owner.",
                f"Source: {wardn_ownership.get('source') or 'wardn.json'}.",
            ],
        )
    partner_support = partner_support_summary(version.name, trust, version.owner_organization_id)
    if any(support.support_level == "official" for support in partner_support):
        return trust_component(
            key="ownerVerification",
            label="Owner verification",
            score=100,
            summary="Official partner support is active.",
            evidence=["At least one active partner marks this server as official."],
        )
    if partner_support:
        return trust_component(
            key="ownerVerification",
            label="Owner verification",
            score=85,
            summary="Partner support metadata is active.",
            evidence=[
                "Support levels: "
                + ", ".join(sorted({support.support_level for support in partner_support}))
                + "."
            ],
        )
    if version.owner_organization_id is not None:
        return trust_component(
            key="ownerVerification",
            label="Owner verification",
            score=75,
            summary="Version is owned by an organization account.",
            evidence=["Organization ownership is recorded in Wardn Hub."],
        )
    if version.owner_user_id is not None or version.publisher_user_id is not None:
        return trust_component(
            key="ownerVerification",
            label="Owner verification",
            score=60,
            summary="Version is associated with a Wardn Hub user account.",
            evidence=["User ownership or publisher identity is recorded."],
        )
    return trust_component(
        key="ownerVerification",
        label="Owner verification",
        score=20,
        summary="No owner verification metadata is published.",
        evidence=["Claim or verify this listing to improve trust."],
    )


def component_security_review(version: RegistryServerVersion) -> RegistryTrustReportComponent:
    server_json = registry_record(version.server_json)
    meta = registry_record(server_json.get("_meta"))
    security_review = registry_record(meta.get("securityReview") or meta.get("security"))
    status = str(security_review.get("status") or "").lower()
    if (
        status in {"approved", "passed", "reviewed", "complete"}
        or security_review.get("reviewed") is True
    ):
        return trust_component(
            key="securityReview",
            label="Security review",
            score=100,
            summary="Security review metadata is published.",
            evidence=[f"Security review status: {status or 'reviewed'}."],
        )
    channels = source_review_channels(meta)
    limitations_reviewed = any(
        review.get("limitationsReviewed") is True for _channel, review in channels
    )
    secret_fields = 0
    for package in registry_records(version.packages):
        secret_fields += sum(
            1
            for item in registry_records(package.get("environmentVariables"))
            if item.get("isSecret") is True
        )
    for remote in registry_records(version.remotes):
        secret_fields += sum(
            1
            for item in registry_records(remote.get("headers"))
            if item.get("isSecret") is True
        )
        secret_fields += sum(
            1
            for item in registry_records(remote.get("queryParameters"))
            if item.get("isSecret") is True
        )
    if limitations_reviewed:
        return trust_component(
            key="securityReview",
            label="Security review",
            score=70,
            summary="Limitations were reviewed, but no dedicated security review is published.",
            evidence=[f"{secret_fields} secret field(s) are marked as secret."],
        )
    return trust_component(
        key="securityReview",
        label="Security review",
        score=30,
        summary="No dedicated security review metadata is published.",
        evidence=["Publish security review metadata or source-review limitations evidence."],
    )


def calculated_trust_score(components: list[RegistryTrustReportComponent]) -> int | None:
    weights = {
        "schemaCompleteness": 15,
        "documentation": 15,
        "sourceReview": 20,
        "targetMetadata": 15,
        "license": 10,
        "maintenance": 10,
        "ownerVerification": 10,
        "securityReview": 5,
    }
    scored = [
        (component.score, weights.get(component.key, 0))
        for component in components
        if component.score is not None
    ]
    total_weight = sum(weight for _score, weight in scored)
    if total_weight <= 0:
        return None
    return round(sum((score or 0) * weight for score, weight in scored) / total_weight)


def trust_report_for_version(
    version: RegistryServerVersion,
    *,
    trust: RegistryTrustContext = EMPTY_TRUST_CONTEXT,
) -> RegistryTrustReport:
    meta = registry_record(registry_record(version.server_json).get("_meta"))
    stored_report = registry_record(meta.get("wardnTrustReport"))
    if stored_report:
        try:
            report = RegistryTrustReport.model_validate(stored_report)
        except ValueError:
            pass
        else:
            owner_component = component_owner_verification(version, trust)
            replaced = False
            for index, component in enumerate(report.components):
                if component.key == "ownerVerification":
                    report.components[index] = owner_component
                    replaced = True
                    break
            if not replaced:
                report.components.append(owner_component)
            if version.quality_score is not None and report.overall_score != version.quality_score:
                report.overall_score = version.quality_score
                report.score_source = "manual"
                report.status = trust_status(version.quality_score)
            return report

    components = [
        component_schema_completeness(version),
        component_documentation(version),
        component_source_review(version),
        component_target_metadata(version),
        component_license(version),
        component_maintenance(version),
        component_owner_verification(version, trust),
        component_security_review(version),
    ]
    calculated_score = calculated_trust_score(components)
    overall_score = version.quality_score if version.quality_score is not None else calculated_score
    if version.quality_score is not None:
        score_source = "manual"
    elif overall_score is not None:
        score_source = "calculated"
    else:
        score_source = "pending"
    weak_components = [
        component.label
        for component in components
        if component.status in {"failed", "unknown"}
    ]
    if overall_score is None:
        summary = (
            "Trust report is pending because there is not enough metadata to score this version."
        )
    elif weak_components:
        summary = "Trust report has gaps: " + ", ".join(weak_components[:4]) + "."
    else:
        summary = "Trust report has no major metadata gaps."
    return RegistryTrustReport(
        overall_score=overall_score,
        score_source=score_source,
        status=trust_status(overall_score),
        summary=summary,
        components=components,
    )


def category_values_by_server_from_versions(
    versions: list[RegistryServerVersion],
    server_ids: set[UUID],
) -> dict[UUID, list[str]]:
    values_by_server: dict[UUID, list[str]] = {}
    for version in versions:
        if version.server_id not in server_ids or version.server_id in values_by_server:
            continue
        values = category_values_from_server_json(version.server_json or {})
        if values:
            values_by_server[version.server_id] = values
    return values_by_server


def public_user_name(user) -> str:
    display_name = getattr(user, "display_name", "")
    if display_name:
        return display_name
    return f"{user.first_name} {user.last_name}".strip()


def public_user_login(user) -> str:
    return public_user_name(user) or str(user.id)


def actor_summary_for_user(user) -> ActorSummary:
    return ActorSummary(
        id=user.id,
        login=public_user_login(user),
        type="User",
        name=public_user_name(user),
        url=f"/api/v1/users/{user.id}",
        htmlUrl=f"/users/{user.id}",
    )


def public_user_summary(user) -> RegistryUserRead:
    return RegistryUserRead(
        id=user.id,
        login=public_user_login(user),
        name=public_user_name(user),
        htmlUrl=f"/users/{user.id}",
    )


def actor_summary_for_organization(organization) -> ActorSummary:
    return ActorSummary(
        id=organization.id,
        login=organization.slug,
        type="Organization",
        name=organization.name,
        url=f"/api/v1/organizations/{organization.id}",
        htmlUrl=f"/{organization.slug}",
    )


def user_actor(user_id: UUID | None, trust: RegistryTrustContext) -> ActorSummary | None:
    if user_id is None:
        return None
    user = trust.users.get(user_id)
    return actor_summary_for_user(user) if user is not None else None


def organization_actor(
    organization_id: UUID | None,
    trust: RegistryTrustContext,
) -> ActorSummary | None:
    if organization_id is None:
        return None
    organization = trust.organizations.get(organization_id)
    return actor_summary_for_organization(organization) if organization is not None else None


def owner_actor(
    *,
    owner_user_id: UUID | None,
    owner_organization_id: UUID | None,
    trust: RegistryTrustContext,
) -> ActorSummary | None:
    return organization_actor(owner_organization_id, trust) or user_actor(owner_user_id, trust)


def partner_support_summary(
    server_name: str,
    trust: RegistryTrustContext,
    owner_organization_id: UUID | None = None,
) -> list[PartnerSupportSummary]:
    summaries = []
    seen_organization_ids: set[UUID] = set()
    owner_organization = (
        trust.organizations.get(owner_organization_id)
        if owner_organization_id is not None
        else None
    )
    for support, organization in trust.partner_support.get(server_name, []):
        summaries.append(
            PartnerSupportSummary(
                organization=actor_summary_for_organization(organization),
                supportLevel=support.support_level,
                supportStatus=support.support_status,
                supportUrl=support.support_url,
                docsUrl=support.docs_url,
                startsAt=support.starts_at,
                endsAt=support.ends_at,
            )
        )
        seen_organization_ids.add(organization.id)

    if (
        owner_organization is not None
        and owner_organization.is_partner
        and owner_organization.partner_status == "active"
        and owner_organization.id not in seen_organization_ids
    ):
        summaries.append(
            PartnerSupportSummary(
                organization=actor_summary_for_organization(owner_organization),
                supportLevel=owner_organization.partner_support_level or "compatible",
                supportStatus="active",
                supportUrl=owner_organization.website_url,
                docsUrl="",
                startsAt=None,
                endsAt=None,
            )
        )
        seen_organization_ids.add(owner_organization.id)
    return summaries


def category_summary(category: RegistryCategory) -> RegistryCategoryRead:
    return RegistryCategoryRead(
        id=category.id,
        slug=category.slug,
        name=category.name,
        description=category.description,
        sortOrder=category.sort_order,
    )


def next_category_sort_order(
    existing_orders: list[int],
    requested_order: int | None = None,
) -> int:
    used_orders = set(existing_orders)
    candidate = (
        requested_order if requested_order is not None else (max(used_orders, default=0) + 10)
    )
    while candidate in used_orders:
        candidate += 10
    return candidate


def categories_for_server(
    server_id: UUID,
    trust: RegistryTrustContext,
) -> list[RegistryCategoryRead]:
    return [category_summary(category) for category in trust.categories.get(server_id, [])]


async def sync_server_categories_if_present(
    session,
    server_id: UUID,
    category_slugs: list[str],
) -> None:
    if category_slugs:
        await repository.sync_server_categories(session, server_id, category_slugs)


async def build_trust_context(
    session,
    *,
    servers: list[RegistryServer] | None = None,
    versions: list[RegistryServerVersion] | None = None,
) -> RegistryTrustContext:
    servers = servers or []
    versions = versions or []
    user_ids: set[UUID] = set()
    organization_ids: set[UUID] = set()
    server_names = {server.name for server in servers} | {version.name for version in versions}

    for server in servers:
        for user_id in (server.owner_user_id, server.created_by_user_id, server.updated_by_user_id):
            if user_id is not None:
                user_ids.add(user_id)
        if server.owner_organization_id is not None:
            organization_ids.add(server.owner_organization_id)

    for version in versions:
        for user_id in (
            version.owner_user_id,
            version.created_by_user_id,
            version.updated_by_user_id,
            version.publisher_user_id,
        ):
            if user_id is not None:
                user_ids.add(user_id)
        if version.owner_organization_id is not None:
            organization_ids.add(version.owner_organization_id)

    partner_support = await repository.list_partner_support_for_servers(session, server_names)
    for records in partner_support.values():
        for _support, organization in records:
            organization_ids.add(organization.id)

    server_ids = {server.id for server in servers} | {version.server_id for version in versions}
    categories = await repository.list_categories_for_servers(
        session,
        server_ids,
    )
    missing_category_server_ids = {
        server_id
        for server_id in server_ids
        if not categories.get(server_id)
    }
    fallback_category_slugs = category_values_by_server_from_versions(
        versions,
        missing_category_server_ids,
    )
    categories_by_slug = await repository.list_categories_by_slugs(
        session,
        {slug for slugs in fallback_category_slugs.values() for slug in slugs},
    )
    for server_id, slugs in fallback_category_slugs.items():
        fallback_categories = [
            categories_by_slug[slug] for slug in slugs if slug in categories_by_slug
        ]
        if fallback_categories:
            categories[server_id] = fallback_categories

    return RegistryTrustContext(
        users=await repository.list_users_by_ids(session, user_ids),
        organizations=await repository.list_organizations_by_ids(session, organization_ids),
        partner_support=partner_support,
        categories=categories,
    )


def server_summary(
    server: RegistryServer,
    latest_version: RegistryServerVersion | None = None,
    *,
    trust: RegistryTrustContext = EMPTY_TRUST_CONTEXT,
) -> RegistryServerRead:
    latest = None
    if latest_version is not None:
        latest = RegistryLatestVersionSummary(
            id=latest_version.id,
            version=latest_version.version,
            status=latest_version.status,
            quality_score=latest_version.quality_score,
            trust_report=trust_report_for_version(latest_version, trust=trust),
            published_at=latest_version.published_at,
            published_by=user_actor(latest_version.publisher_user_id, trust),
        )
    return RegistryServerRead(
        id=server.id,
        name=server.name,
        title=server.title,
        description=server.description,
        documentation=server.documentation,
        website_url=server.website_url,
        repository=server.repository,
        icons=server.icons,
        status=server.status,
        status_message=server.status_message,
        visibility=server.visibility,
        owner=owner_actor(
            owner_user_id=server.owner_user_id,
            owner_organization_id=server.owner_organization_id,
            trust=trust,
        ),
        organization=organization_actor(server.owner_organization_id, trust),
        created_by=user_actor(server.created_by_user_id, trust),
        updated_by=user_actor(server.updated_by_user_id, trust),
        latest_version=latest,
        quality_score=latest_version.quality_score if latest_version is not None else None,
        trust_report=(
            trust_report_for_version(latest_version, trust=trust)
            if latest_version is not None
            else None
        ),
        categories=categories_for_server(server.id, trust),
        partner_support=partner_support_summary(
            server.name,
            trust,
            server.owner_organization_id,
        ),
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


def version_summary(
    version: RegistryServerVersion,
    *,
    include_private_metadata: bool = True,
    trust: RegistryTrustContext = EMPTY_TRUST_CONTEXT,
) -> RegistryServerVersionRead:
    packages = (
        version.packages
        if include_private_metadata
        else public_registry_json(version.packages)
    )
    normalized_remotes = registry_remotes_json(version.remotes)
    remotes = (
        normalized_remotes
        if include_private_metadata
        else public_registry_json(normalized_remotes)
    )
    server_json = (
        version.server_json
        if include_private_metadata
        else public_registry_json(version.server_json)
    )
    return RegistryServerVersionRead(
        id=version.id,
        server_id=version.server_id,
        name=version.name,
        version=version.version,
        title=version.title,
        description=version.description,
        documentation=version.documentation,
        website_url=version.website_url,
        repository=version.repository,
        packages=packages,
        remotes=remotes,
        icons=version.icons,
        server_json=server_json,
        quality_score=version.quality_score,
        trust_report=trust_report_for_version(version, trust=trust),
        status=version.status,
        status_message=version.status_message,
        is_latest=version.is_latest,
        owner=owner_actor(
            owner_user_id=version.owner_user_id,
            owner_organization_id=version.owner_organization_id,
            trust=trust,
        ),
        organization=organization_actor(version.owner_organization_id, trust),
        created_by=user_actor(version.created_by_user_id, trust),
        updated_by=user_actor(version.updated_by_user_id, trust),
        published_by=user_actor(version.publisher_user_id, trust),
        partner_support=partner_support_summary(
            version.name,
            trust,
            version.owner_organization_id,
        ),
        published_at=version.published_at,
        status_changed_at=version.status_changed_at,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


def published_version_summary(version: RegistryServerVersion) -> RegistryPublishedServerVersionRead:
    return RegistryPublishedServerVersionRead(
        id=version.id,
        version=version.version,
        quality_score=version.quality_score,
        trust_report=trust_report_for_version(version),
        packages=public_registry_json(version.packages),
        remotes=public_registry_json(registry_remotes_json(version.remotes)),
        status=version.status,
        status_message=version.status_message,
        is_latest=version.is_latest,
        published_at=version.published_at,
        status_changed_at=version.status_changed_at,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


def catalog_server_summary(
    server: RegistryServer,
    latest_version: RegistryServerVersion,
    versions: list[RegistryServerVersion],
    *,
    trust: RegistryTrustContext = EMPTY_TRUST_CONTEXT,
) -> RegistryCatalogServerRead:
    return RegistryCatalogServerRead(
        **server_summary(server, latest_version, trust=trust).model_dump(by_alias=True),
        versions=[published_version_summary(version) for version in versions],
    )


async def server_with_latest(session, server: RegistryServer) -> RegistryServerRead:
    latest = None
    if server.current_version_id:
        latest = await repository.get_server_version(session, server.name, "latest")
    trust = await build_trust_context(
        session,
        servers=[server],
        versions=[latest] if latest else [],
    )
    return server_summary(server, latest, trust=trust)


async def create_server_version(
    session,
    payload: RegistryServerVersionCreate,
    *,
    owner_user_id: UUID | None = None,
    owner_organization_id: UUID | None = None,
    created_by_user_id: UUID | None = None,
    updated_by_user_id: UUID | None = None,
    publisher_user_id: UUID | None = None,
) -> RegistryServerVersionDetailResponse:
    existing_version = await repository.get_server_version(
        session,
        payload.name,
        payload.version,
        include_deleted=True,
    )
    if existing_version is not None and existing_version.status != "deleted":
        raise DuplicateRegistryVersionError("server version already exists")

    server = await repository.get_server(session, payload.name, include_deleted=True)
    should_emit_server_published = server is None or server.status == "deleted"
    values = document_values(payload)
    now = datetime.now(UTC)

    if server is None:
        server = RegistryServer(
            name=payload.name,
            owner_user_id=owner_user_id,
            owner_organization_id=owner_organization_id,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=updated_by_user_id,
            title=payload.title,
            description=payload.description,
            documentation=payload.documentation,
            website_url=payload.website_url,
            repository=values["repository"],
            icons=values["icons"],
            status="active",
            status_message="",
            visibility="public",
        )
        session.add(server)
        await session.flush()
        await session.refresh(server)
    else:
        if owner_user_id is not None or owner_organization_id is not None:
            server.owner_user_id = owner_user_id
            server.owner_organization_id = owner_organization_id
        if updated_by_user_id is not None:
            server.updated_by_user_id = updated_by_user_id
        server.title = payload.title
        server.description = payload.description
        server.documentation = payload.documentation
        server.website_url = payload.website_url
        server.repository = values["repository"]
        server.icons = values["icons"]
        if server.status == "deleted":
            server.status = "active"
            server.status_message = ""

    await repository.clear_latest_for_server(session, server.id)

    if existing_version is not None:
        for key, value in values.items():
            if key != "version":
                setattr(existing_version, key, value)
        existing_version.status = "active"
        existing_version.status_message = ""
        existing_version.is_latest = True
        if owner_user_id is not None or owner_organization_id is not None:
            existing_version.owner_user_id = owner_user_id
            existing_version.owner_organization_id = owner_organization_id
        if updated_by_user_id is not None:
            existing_version.updated_by_user_id = updated_by_user_id
        if publisher_user_id is not None:
            existing_version.publisher_user_id = publisher_user_id
        existing_version.status_changed_at = now
        version = existing_version
    else:
        version = RegistryServerVersion(
            server_id=server.id,
            **values,
            owner_user_id=owner_user_id,
            owner_organization_id=owner_organization_id,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=updated_by_user_id,
            publisher_user_id=publisher_user_id,
            status="active",
            status_message="",
            is_latest=True,
            published_at=now,
            status_changed_at=now,
        )
        session.add(version)

    await session.flush()
    await session.refresh(version)
    server.current_version_id = version.id
    await sync_server_categories_if_present(session, server.id, category_values(payload))
    await session.flush()
    await session.refresh(server)
    actor_user_id = publisher_user_id or updated_by_user_id or created_by_user_id
    if should_emit_server_published:
        await emit_registry_server_event(
            session,
            event_type="registry.server.published",
            server=server,
            actor_user_id=actor_user_id,
            occurred_at=now,
        )
    await emit_registry_version_event(
        session,
        event_type="registry.version.published",
        version=version,
        actor_user_id=actor_user_id,
        occurred_at=now,
    )
    trust = await build_trust_context(session, servers=[server], versions=[version])
    return RegistryServerVersionDetailResponse(
        server=server_summary(server, version, trust=trust),
        version=version_summary(version, trust=trust),
    )


async def update_server_version(
    session,
    name: str,
    version_name: str,
    payload: RegistryServerVersionUpdate,
    *,
    updated_by_user_id: UUID | None = None,
) -> RegistryServerVersionDetailResponse:
    if payload.name != name or payload.version != version_name:
        raise RegistryVersionNotFoundError("server version does not match request path")

    version = await repository.get_server_version(
        session,
        name,
        version_name,
        include_deleted=True,
    )
    if version is None:
        raise RegistryVersionNotFoundError("server version not found")

    server = await repository.get_server_by_id(session, version.server_id)
    if server is None:
        raise RegistryServerNotFoundError("server not found")

    values = document_values(payload)
    for key, value in values.items():
        setattr(version, key, value)
    if updated_by_user_id is not None:
        version.updated_by_user_id = updated_by_user_id
    if version.status == "deleted":
        version.status = "active"
        version.status_message = ""
        version.status_changed_at = datetime.now(UTC)

    if version.is_latest:
        server.title = payload.title
        server.description = payload.description
        server.website_url = payload.website_url
        server.repository = values["repository"]
        server.icons = values["icons"]
        if updated_by_user_id is not None:
            server.updated_by_user_id = updated_by_user_id
        await sync_server_categories_if_present(session, server.id, category_values(payload))

    await session.flush()
    await session.refresh(version)
    await session.refresh(server)
    trust = await build_trust_context(session, servers=[server], versions=[version])
    return RegistryServerVersionDetailResponse(
        server=server_summary(server, version if version.is_latest else None, trust=trust),
        version=version_summary(version, trust=trust),
    )


async def update_version_quality_score(
    session,
    name: str,
    version_name: str,
    quality_score: int,
    trust_report: RegistryTrustReport | None = None,
) -> RegistryServerVersionDetailResponse:
    version = await repository.get_server_version(
        session,
        name,
        version_name,
        include_deleted=True,
    )
    if version is None:
        raise RegistryVersionNotFoundError("server version not found")

    server = await repository.get_server_by_id(session, version.server_id)
    if server is None:
        raise RegistryServerNotFoundError("server not found")

    version.quality_score = quality_score
    if trust_report is not None:
        server_json = dict(version.server_json or {})
        meta = dict(registry_record(server_json.get("_meta")))
        meta["wardnTrustReport"] = trust_report.model_dump(by_alias=True)
        server_json["_meta"] = meta
        version.server_json = server_json
    await session.flush()
    await session.refresh(version)
    await session.refresh(server)

    latest = version if version.is_latest else None
    if latest is None and server.current_version_id is not None:
        latest = await repository.get_server_version(session, server.name, "latest")
    trust = await build_trust_context(
        session,
        servers=[server],
        versions=[candidate for candidate in (version, latest) if candidate is not None],
    )
    return RegistryServerVersionDetailResponse(
        server=server_summary(server, latest, trust=trust),
        version=version_summary(version, trust=trust),
    )


async def delete_server_version(
    session,
    name: str,
    version_name: str,
    *,
    actor_user_id: UUID | None = None,
) -> None:
    version = await repository.get_server_version(
        session,
        name,
        version_name,
        include_deleted=True,
    )
    if version is None:
        raise RegistryVersionNotFoundError("server version not found")
    if version.status == "deleted":
        return

    server = await repository.get_server_by_id(session, version.server_id)
    if server is None:
        raise RegistryServerNotFoundError("server not found")

    was_latest = version.is_latest
    version.status = "deleted"
    version.status_message = "Deleted from Wardn Hub."
    version.is_latest = False
    version.status_changed_at = datetime.now(UTC)

    if was_latest:
        replacement = await repository.latest_visible_version(session, server.id)
        if replacement is not None:
            replacement.is_latest = True
            server.current_version_id = replacement.id
            server.title = replacement.title
            server.description = replacement.description
            server.website_url = replacement.website_url
            server.repository = replacement.repository
            server.icons = replacement.icons
        else:
            server.status = "deleted"
            server.status_message = "All versions deleted from Wardn Hub."
            server.current_version_id = None
            await emit_registry_server_event(
                session,
                event_type="registry.server.archived",
                server=server,
                actor_user_id=actor_user_id,
                occurred_at=version.status_changed_at,
            )

    await session.flush()


async def delete_server(
    session,
    name: str,
    *,
    actor_user_id: UUID | None = None,
) -> None:
    server = await repository.get_server(session, name, include_deleted=True)
    if server is None:
        raise RegistryServerNotFoundError("server not found")
    if server.status == "deleted":
        return

    now = datetime.now(UTC)
    versions = await repository.list_server_versions(
        session,
        name,
        include_deleted=True,
    )
    for version in versions:
        version.status = "deleted"
        version.status_message = "Deleted from Wardn Hub."
        version.is_latest = False
        version.status_changed_at = now

    server.status = "deleted"
    server.status_message = "All versions deleted from Wardn Hub."
    server.current_version_id = None
    await repository.sync_server_categories(session, server.id, [])
    await emit_registry_server_event(
        session,
        event_type="registry.server.archived",
        server=server,
        actor_user_id=actor_user_id,
        occurred_at=now,
    )
    await session.flush()


async def set_latest_version(
    session,
    name: str,
    version_name: str,
) -> RegistryServerVersionDetailResponse:
    version = await repository.get_server_version(session, name, version_name)
    if version is None:
        raise RegistryVersionNotFoundError("server version not found")
    server = await repository.get_server_by_id(session, version.server_id)
    if server is None:
        raise RegistryServerNotFoundError("server not found")

    await repository.clear_latest_for_server(session, server.id)
    version.is_latest = True
    server.current_version_id = version.id
    server.title = version.title
    server.description = version.description
    server.website_url = version.website_url
    server.repository = version.repository
    server.icons = version.icons
    await sync_server_categories_if_present(
        session,
        server.id,
        category_values_from_server_json(version.server_json),
    )
    await session.flush()
    await session.refresh(version)
    await session.refresh(server)
    trust = await build_trust_context(session, servers=[server], versions=[version])
    return RegistryServerVersionDetailResponse(
        server=server_summary(server, version, trust=trust),
        version=version_summary(version, trust=trust),
    )


async def list_servers(
    session,
    *,
    cursor: str | None,
    limit: int,
    search: str | None = None,
    updated_since=None,
    version: str | None = "latest",
    support_level: str | None = None,
    partner: bool | None = None,
    registry_type: str | None = None,
    transport_type: str | None = None,
    status: str | None = None,
    category: str | None = None,
) -> RegistryServerListResponse:
    offset = parse_cursor(cursor)
    servers, next_cursor = await repository.list_servers(
        session,
        offset=offset,
        limit=limit,
        include_deleted=False,
        search=search,
        updated_since=updated_since,
        version=version,
        support_level=support_level,
        partner=partner,
        registry_type=registry_type,
        transport_type=transport_type,
        category=category,
        status=status,
    )
    return RegistryServerListResponse(
        servers=[await server_with_latest(session, server) for server in servers],
        metadata=RegistryListMetadata(count=len(servers), next_cursor=next_cursor),
    )


async def list_published_servers(
    session,
    *,
    page: int,
    per_page: int = 20,
) -> RegistryPublishedServerListResponse:
    offset = (page - 1) * per_page
    rows, total = await repository.list_published_servers(
        session,
        offset=offset,
        limit=per_page,
    )
    servers = [server for server, _version in rows]
    versions_by_server = await repository.list_published_versions_for_servers(
        session,
        {server.id for server in servers},
    )
    published_versions = [
        version
        for server in servers
        for version in versions_by_server.get(server.id, [])
    ]
    missing_latest_versions = [
        version for server, version in rows if not versions_by_server.get(server.id)
    ]
    versions = published_versions + missing_latest_versions
    trust = await build_trust_context(session, servers=servers, versions=versions)
    return RegistryPublishedServerListResponse(
        servers=[
            catalog_server_summary(
                server,
                version,
                versions_by_server.get(server.id, [version]),
                trust=trust,
            )
            for server, version in rows
        ],
        metadata=RegistryPageMetadata(
            page=page,
            perPage=per_page,
            total=total,
            pages=(total + per_page - 1) // per_page,
        ),
    )


async def list_categories(session) -> RegistryCategoryListResponse:
    categories = await repository.list_categories(session)
    return RegistryCategoryListResponse(
        categories=[category_summary(category) for category in categories]
    )


async def create_category(
    session,
    payload: RegistryCategoryCreate,
) -> RegistryCategoryRead:
    slug = category_slug(payload.slug)
    existing = await repository.get_category_by_slug(session, slug, include_deleted=True)
    if existing is not None:
        raise DuplicateRegistryCategoryError("category slug already exists")

    existing_orders = await repository.list_category_sort_orders(session)
    category = await repository.create_category(
        session,
        slug=slug,
        name=payload.name.strip(),
        description=payload.description.strip(),
        sort_order=next_category_sort_order(existing_orders, payload.sort_order),
    )
    return category_summary(category)


async def update_category(
    session,
    category_slug_value: str,
    payload: RegistryCategoryUpdate,
) -> RegistryCategoryRead:
    current_slug = category_slug(category_slug_value)
    category = await repository.get_category_by_slug(session, current_slug)
    if category is None:
        raise RegistryCategoryNotFoundError("category not found")

    next_slug = category_slug(payload.slug) if payload.slug is not None else None
    if next_slug is not None and next_slug != current_slug:
        existing = await repository.get_category_by_slug(session, next_slug, include_deleted=True)
        if existing is not None:
            raise DuplicateRegistryCategoryError("category slug already exists")

    sort_order = None
    if payload.sort_order is not None:
        existing_orders = await repository.list_category_sort_orders(
            session,
            exclude_category_id=category.id,
        )
        sort_order = next_category_sort_order(existing_orders, payload.sort_order)

    category = await repository.update_category(
        session,
        category,
        slug=next_slug,
        name=payload.name.strip() if payload.name is not None else None,
        description=payload.description.strip() if payload.description is not None else None,
        sort_order=sort_order,
    )
    return category_summary(category)


async def delete_category(session, category_slug_value: str) -> None:
    slug = category_slug(category_slug_value)
    category = await repository.get_category_by_slug(session, slug)
    if category is None:
        raise RegistryCategoryNotFoundError("category not found")
    await repository.delete_category(session, category)


async def list_registry_users(session) -> RegistryUserListResponse:
    users = await repository.list_public_registry_users(session)
    return RegistryUserListResponse(users=[public_user_summary(user) for user in users])


async def get_registry_user_detail(
    session,
    user_id: UUID,
    *,
    cursor: str | None,
    limit: int,
) -> RegistryUserDetailResponse:
    user = (await repository.list_users_by_ids(session, {user_id})).get(user_id)
    if user is None or not user.is_active:
        raise UserNotFoundError("user not found")

    offset = parse_cursor(cursor)
    servers, next_cursor = await repository.list_servers_for_user(
        session,
        user_id,
        offset=offset,
        limit=limit,
    )
    return RegistryUserDetailResponse(
        user=public_user_summary(user),
        servers=[await server_with_latest(session, server) for server in servers],
        metadata=RegistryListMetadata(count=len(servers), next_cursor=next_cursor),
    )


async def seed_default_categories(session) -> RegistryCategoryListResponse:
    categories = await repository.seed_categories(session, MCP_SERVERS_CATEGORY_SEEDS)
    return RegistryCategoryListResponse(
        categories=[category_summary(category) for category in categories]
    )


def same_ownership_repository(
    left: WardnOwnershipRepository | None,
    right: WardnOwnershipRepository | None,
) -> bool:
    if left is None or right is None:
        return False
    return left.owner.lower() == right.owner.lower() and left.repo.lower() == right.repo.lower()


def same_ownership_website(left: str, right: str) -> bool:
    left_url = wardn_ownership_website_url(left)
    right_url = wardn_ownership_website_url(right)
    return bool(left_url and right_url and left_url == right_url)


async def claim_server_ownership(
    session,
    name: str,
    current_user,
) -> RegistryOwnershipClaimResponse:
    server = await repository.get_published_server(session, name)
    if server is None:
        raise RegistryServerNotFoundError("server not found")
    versions = await repository.list_published_server_versions(session, server)
    latest = next((candidate for candidate in versions if candidate.is_latest), None)
    repository_ref = github_repository_from_registry_repository(
        latest.repository if latest and latest.repository else server.repository
    )
    website_url = (
        latest.website_url if latest and latest.website_url else server.website_url
    ) or ""
    if repository_ref is None and not wardn_ownership_website_url(website_url):
        raise RegistryOwnershipClaimError(
            "server must reference a GitHub repository or website URL to use wardn.json"
        )
    if server.owner_organization_id is not None or any(
        version.owner_organization_id is not None for version in versions
    ):
        raise RegistryOwnershipClaimConflictError(
            "organization-owned servers require organization transfer or moderator review"
        )

    manifest: WardnOwnershipManifest | None = None
    source_repository_ref: WardnOwnershipRepository | None = None
    source_website_url = ""
    claim_errors: list[str] = []
    if repository_ref is not None:
        try:
            manifest = await fetch_wardn_ownership_manifest(repository_ref)
            source_repository_ref = repository_ref
        except RegistryOwnershipClaimError as exc:
            claim_errors.append(str(exc))
    if manifest is None and wardn_ownership_website_url(website_url):
        try:
            manifest = await fetch_wardn_ownership_manifest_from_website(website_url)
            source_website_url = website_url
        except RegistryOwnershipClaimError as exc:
            claim_errors.append(str(exc))
    if manifest is None:
        raise RegistryOwnershipClaimError(
            claim_errors[-1]
            if claim_errors
            else "wardn.json was not found in the linked GitHub repository or website root"
        )

    owner_ids = owner_user_ids_from_manifest(manifest.payload, server.name)
    if current_user.id not in owner_ids:
        raise RegistryOwnershipClaimError("wardn.json does not list the current Wardn user UUID")

    verified_at = datetime.now(UTC)
    server.owner_user_id = current_user.id
    server.updated_by_user_id = current_user.id
    for version in versions:
        if source_repository_ref is not None:
            version_repository_ref = github_repository_from_registry_repository(
                version.repository or server.repository
            )
            if not same_ownership_repository(source_repository_ref, version_repository_ref):
                continue
        elif not same_ownership_website(
            source_website_url,
            version.website_url or server.website_url,
        ):
            continue
        version.owner_user_id = current_user.id
        version.updated_by_user_id = current_user.id
        attach_wardn_ownership_metadata(
            version,
            user_id=current_user.id,
            source_url=manifest.source_url,
            verified_at=verified_at,
        )
    await session.flush()

    detail = await get_server_detail(session, name)
    return RegistryOwnershipClaimResponse(
        **detail.model_dump(by_alias=True),
        verified=True,
        verificationSource=manifest.source_url,
    )


async def get_server_detail(
    session,
    name: str,
) -> RegistryServerDetailResponse:
    server = await repository.get_published_server(session, name)
    if server is None:
        raise RegistryServerNotFoundError("server not found")
    versions = await repository.list_published_server_versions(session, server)
    latest = next((candidate for candidate in versions if candidate.is_latest), None)
    trust = await build_trust_context(session, servers=[server], versions=versions)
    return RegistryServerDetailResponse(
        server=server_summary(server, latest, trust=trust),
        versions=[
            version_summary(version, include_private_metadata=False, trust=trust)
            for version in versions
        ],
    )


async def list_versions(
    session,
    name: str,
) -> RegistryServerVersionListResponse:
    server = await repository.get_published_server(session, name)
    if server is None:
        raise RegistryServerNotFoundError("server not found")
    versions = await repository.list_published_server_versions(session, server)
    trust = await build_trust_context(session, versions=versions)
    return RegistryServerVersionListResponse(
        versions=[
            version_summary(version, include_private_metadata=False, trust=trust)
            for version in versions
        ],
        metadata=RegistryListMetadata(count=len(versions)),
    )


async def get_version_detail(
    session,
    name: str,
    version_name: str,
) -> RegistryServerVersionDetailResponse:
    server = await repository.get_published_server(session, name)
    if server is None:
        raise RegistryServerNotFoundError("server not found")
    version = await repository.get_published_server_version(session, server, version_name)
    if version is None:
        raise RegistryVersionNotFoundError("server version not found")
    latest = (
        version
        if version.is_latest
        else await repository.get_published_server_version(session, server, "latest")
    )
    trust = await build_trust_context(
        session,
        servers=[server],
        versions=[candidate for candidate in (version, latest) if candidate is not None],
    )
    support = partner_support_summary(version.name, trust)
    return RegistryServerVersionDetailResponse(
        server=server_summary(server, latest, trust=trust),
        version=version_summary(version, include_private_metadata=False, trust=trust),
        support={"partnerSupport": [item.model_dump(by_alias=True) for item in support]},
    )
