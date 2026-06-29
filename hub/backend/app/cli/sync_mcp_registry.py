from __future__ import annotations

import argparse
import copy
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from app.modules.imports.exceptions import SourceNotFoundError, UnsupportedSourceError
from app.modules.imports.schemas import ServerSourceImportRequest
from app.modules.imports.service import import_server_source

API_PREFIX = "/api/v1"
DEFAULT_HUB_API_BASE_URL = "http://localhost:8000/api/v1"
DEFAULT_REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"
DEFAULT_REGISTRY_RETRIES = 3
DEFAULT_REGISTRY_RETRY_DELAY_SECONDS = 2.0
DEFAULT_CATEGORY = "other-tools-integrations"
INITIAL_SERVER_VERSION = "1.0.0"
HUB_TOKEN_ENV = "WARDN_HUB_TOKEN"
HUB_API_BASE_URL_ENV = "WARDN_HUB_API_BASE_URL"
REGISTRY_URL_ENV = "WARDN_HUB_MCP_REGISTRY_URL"
USER_AGENT_ENV = "WARDN_HUB_USER_AGENT"
DEFAULT_USER_AGENT = "WardnHubMCPRegistrySync/0.1"
OFFICIAL_META_KEY = "io.modelcontextprotocol.registry/official"
IMPORT_META_KEY = "wardnImport"


class UserFacingError(Exception):
    pass


@dataclass(frozen=True)
class HubApiError(UserFacingError):
    status: int
    detail: str
    url: str

    def __str__(self) -> str:
        return f"{self.status} from {self.url}: {self.detail}"


@dataclass
class SyncStats:
    pages: int = 0
    seen: int = 0
    candidate: int = 0
    submitted: int = 0
    draft: int = 0
    skipped: int = 0
    invalid: int = 0
    failed: int = 0


@dataclass(frozen=True)
class ImportOutcome:
    status: str
    reason: str


class HubClient(Protocol):
    def list_submissions(self) -> list[dict[str, Any]]: ...

    def get_server(self, server_name: str) -> dict[str, Any] | None: ...

    def create_submission(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def update_submission(self, submission_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def submit_submission(self, submission_id: str) -> dict[str, Any]: ...


def normalize_api_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        return DEFAULT_HUB_API_BASE_URL
    if normalized.endswith(API_PREFIX):
        return normalized
    return normalized + API_PREFIX


def parse_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason_phrase
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list) and detail:
            first = detail[0]
            if isinstance(first, dict):
                return str(first.get("msg") or first)
            return str(first)
    return str(payload)


def server_name_path(server_name: str) -> str:
    return quote(server_name, safe="/")


class WardnHubApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float,
        user_agent: str,
    ) -> None:
        self.base_url = normalize_api_base_url(base_url)
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent.strip() or DEFAULT_USER_AGENT
        self._client = httpx.Client(
            timeout=timeout_seconds,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": self.user_agent,
            },
        )

    def close(self) -> None:
        self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        expected_statuses: set[int],
    ) -> httpx.Response:
        response = self._client.request(
            method,
            f"{self.base_url}{path}",
            json=payload,
        )
        if response.status_code not in expected_statuses:
            raise HubApiError(response.status_code, parse_error_detail(response), str(response.url))
        return response

    def list_submissions(self) -> list[dict[str, Any]]:
        response = self.request("GET", "/submissions", expected_statuses={200})
        payload = response.json()
        submissions = payload.get("submissions") if isinstance(payload, dict) else []
        return submissions if isinstance(submissions, list) else []

    def get_server(self, server_name: str) -> dict[str, Any] | None:
        try:
            response = self.request(
                "GET",
                f"/mcp/servers/{server_name_path(server_name)}",
                expected_statuses={200},
            )
        except HubApiError as exc:
            if exc.status == 404:
                return None
            raise
        return response.json()

    def create_submission(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.request("POST", "/submissions", payload=payload, expected_statuses={201})
        return response.json()

    def update_submission(self, submission_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.request(
            "PUT",
            f"/submissions/{quote(submission_id, safe='')}",
            payload=payload,
            expected_statuses={200},
        )
        return response.json()

    def submit_submission(self, submission_id: str) -> dict[str, Any]:
        response = self.request(
            "POST",
            f"/submissions/{quote(submission_id, safe='')}/submit",
            expected_statuses={200},
        )
        return response.json()


class MCPRegistryClient:
    def __init__(
        self,
        *,
        registry_url: str,
        timeout_seconds: float,
        user_agent: str,
        retries: int = DEFAULT_REGISTRY_RETRIES,
        retry_delay_seconds: float = DEFAULT_REGISTRY_RETRY_DELAY_SECONDS,
    ) -> None:
        self.registry_url = registry_url.strip() or DEFAULT_REGISTRY_URL
        self.retries = max(1, retries)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)
        self._client = httpx.Client(
            timeout=timeout_seconds,
            headers={"Accept": "application/json", "User-Agent": user_agent or DEFAULT_USER_AGENT},
        )

    def close(self) -> None:
        self._client.close()

    def list_servers(
        self,
        *,
        cursor: str | None,
        limit: int,
        version: str,
        updated_since: str | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "version": version}
        if cursor:
            params["cursor"] = cursor
        if updated_since:
            params["updated_since"] = updated_since

        last_error: httpx.HTTPError | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self._client.get(self.registry_url, params=params)
                break
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise UserFacingError(
                        "official MCP registry request failed after "
                        f"{self.retries} attempt(s): {exc}"
                    ) from exc
                time.sleep(self.retry_delay_seconds)
        else:
            raise UserFacingError("official MCP registry request failed") from last_error

        if response.status_code >= 400:
            raise UserFacingError(
                f"official MCP registry returned {response.status_code} from {response.url}: "
                f"{parse_error_detail(response)}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise UserFacingError("official MCP registry returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise UserFacingError("official MCP registry response must be a JSON object")
        return payload


def parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an RFC3339 datetime") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def official_status(entry: dict[str, Any]) -> str:
    official = entry.get("_meta")
    if isinstance(official, dict):
        official = official.get(OFFICIAL_META_KEY)
    if isinstance(official, dict):
        status = official.get("status")
        if isinstance(status, str):
            return status.strip().lower()
    server = entry.get("server")
    if isinstance(server, dict):
        status = server.get("status")
        if isinstance(status, str):
            return status.strip().lower()
    return ""


def registry_entry_identity(entry: dict[str, Any]) -> tuple[str, str]:
    server = entry.get("server")
    if not isinstance(server, dict):
        return "", ""
    return str(server.get("name") or "").strip(), str(server.get("version") or "").strip()


def verbose_print(enabled: bool, message: str) -> None:
    if enabled:
        print(message, flush=True)


def submission_key(value: dict[str, Any]) -> tuple[str, str]:
    return str(value.get("name") or "").strip(), str(value.get("version") or "").strip()


def existing_submissions_by_key(hub: HubClient) -> dict[tuple[str, str], dict[str, Any]]:
    active_statuses = {"draft", "submitted", "approved", "rejected"}
    status_rank = {"approved": 0, "submitted": 1, "draft": 2, "rejected": 3}
    submissions_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for submission in hub.list_submissions():
        if not isinstance(submission, dict):
            continue
        status = str(submission.get("status") or "")
        if status not in active_statuses:
            continue
        key = submission_key(submission)
        if all(key):
            existing = submissions_by_key.get(key)
            existing_status = str(existing.get("status") or "") if existing else ""
            if existing is None or status_rank[status] < status_rank.get(existing_status, 99):
                submissions_by_key[key] = submission
    return submissions_by_key


def submission_owner_fields(server_detail: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(server_detail, dict):
        return {}
    server = server_detail.get("server")
    if not isinstance(server, dict):
        return {}
    owner = server.get("owner")
    if isinstance(owner, dict) and isinstance(owner.get("id"), str):
        return {"ownerUserId": owner["id"]}
    organization = server.get("organization")
    if isinstance(organization, dict) and isinstance(organization.get("id"), str):
        return {"ownerOrganizationId": organization["id"]}
    return {}


def metadata_categories(meta: dict[str, Any]) -> list[str]:
    candidates: list[Any] = [meta.get("category"), meta.get("categories")]
    publisher = meta.get("io.modelcontextprotocol.registry/publisher-provided")
    if isinstance(publisher, dict):
        candidates.extend([publisher.get("category"), publisher.get("categories")])

    values: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, str):
            values.append(candidate)
        elif isinstance(candidate, list):
            values.extend(item for item in candidate if isinstance(item, str))
    seen: set[str] = set()
    categories = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            categories.append(normalized)
    return categories


def non_empty_strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def package_install_commands(packages: list[Any]) -> list[str]:
    commands: list[str] = []
    for package in packages:
        if not isinstance(package, dict):
            continue
        transport = package.get("transport")
        transport_value = transport if isinstance(transport, dict) else {}
        command = str(transport_value.get("command") or "").strip()
        args = non_empty_strings(transport_value.get("args"))
        if command:
            commands.append(" ".join([command, *args]).strip())
    return commands


def package_command_arguments(packages: list[Any]) -> list[str]:
    values: list[str] = []
    for package in packages:
        if not isinstance(package, dict):
            continue
        transport = package.get("transport")
        transport_value = transport if isinstance(transport, dict) else {}
        values.extend(non_empty_strings(transport_value.get("args")))
    return values


def target_labels(values: list[Any]) -> list[str]:
    labels: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        label = str(value.get("identifier") or value.get("url") or "").strip()
        target_type = str(value.get("registryType") or value.get("type") or "").strip()
        if label:
            labels.append(f"{target_type}:{label}" if target_type else label)
    return labels


def join_or_none(values: list[str]) -> str:
    return ", ".join(values) if values else "None declared."


def starts_at_initial_version(version: str) -> bool:
    return version == INITIAL_SERVER_VERSION


def semver_key(version: str) -> tuple[int, int, int] | None:
    base = version.split("-", 1)[0].split("+", 1)[0]
    parts = base.split(".")
    if len(parts) != 3:
        return None
    try:
        major, minor, patch = (int(part) for part in parts)
    except ValueError:
        return None
    return major, minor, patch


def next_patch_version(version: str) -> str:
    key = semver_key(version)
    if key is None:
        return INITIAL_SERVER_VERSION
    major, minor, patch = key
    return f"{major}.{minor}.{patch + 1}"


def server_detail_versions(server_detail: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(server_detail, dict):
        return []
    versions = server_detail.get("versions")
    if not isinstance(versions, list):
        return []
    return [version for version in versions if isinstance(version, dict)]


def import_upstream_version_from_payload(payload: dict[str, Any]) -> str:
    meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
    import_meta = meta.get(IMPORT_META_KEY) if isinstance(meta.get(IMPORT_META_KEY), dict) else {}
    return str(import_meta.get("upstreamVersion") or payload.get("version") or "").strip()


def import_upstream_version_from_submission(submission: dict[str, Any]) -> str:
    server_json = submission.get("serverJson")
    if not isinstance(server_json, dict):
        server_json = submission.get("server_json")
    payload = server_json if isinstance(server_json, dict) else {}
    return import_upstream_version_from_payload(payload)


def import_upstream_version_from_version(version: dict[str, Any]) -> str:
    server_json = version.get("serverJson")
    if not isinstance(server_json, dict):
        server_json = version.get("server_json")
    payload = server_json if isinstance(server_json, dict) else {}
    return import_upstream_version_from_payload(payload)


def published_import_upstream_versions(server_detail: dict[str, Any] | None) -> set[str]:
    return {
        upstream_version
        for upstream_version in (
            import_upstream_version_from_version(version)
            for version in server_detail_versions(server_detail)
        )
        if upstream_version
    }


def next_wardn_import_version(server_detail: dict[str, Any] | None) -> str:
    versions = []
    for version in server_detail_versions(server_detail):
        candidate = str(version.get("version") or "").strip()
        key = semver_key(candidate)
        if key is not None and key[0] >= 1:
            versions.append((key, candidate))
    if not versions:
        return INITIAL_SERVER_VERSION
    return next_patch_version(max(versions, key=lambda item: item[0])[1])


def apply_wardn_import_version(
    payload: dict[str, Any],
    *,
    server_detail: dict[str, Any] | None,
) -> str | None:
    upstream_version = import_upstream_version_from_payload(payload)
    wardn_version = (
        next_wardn_import_version(server_detail)
        if server_detail is not None
        else INITIAL_SERVER_VERSION
    )
    if payload.get("version") == wardn_version:
        return None
    payload["version"] = wardn_version
    return upstream_version or None


def find_existing_submission_by_upstream_version(
    existing_submissions: dict[tuple[str, str], dict[str, Any]],
    *,
    name: str,
    upstream_version: str,
) -> dict[str, Any] | None:
    if not upstream_version:
        return None
    for (submission_name, _), submission in existing_submissions.items():
        if submission_name != name:
            continue
        if import_upstream_version_from_submission(submission) == upstream_version:
            return submission
    return None


def documentation_has_review_sections(value: str) -> bool:
    lower = value.lower()
    required_terms = {
        "installation": ("installation", "install", "mcpservers", "command"),
        "configuration": ("configuration", "environment", "env", "args", "variables"),
        "capabilities": ("capabilities", "tools", "resources", "prompts"),
    }
    return all(any(term in lower for term in terms) for terms in required_terms.values())


def official_registry_documentation(payload: dict[str, Any]) -> str:
    packages = payload.get("packages") if isinstance(payload.get("packages"), list) else []
    remotes = payload.get("remotes") if isinstance(payload.get("remotes"), list) else []
    install_commands = package_install_commands(packages)
    return "\n".join(
        [
            "## Installation",
            (
                "Package launch commands: " + join_or_none(install_commands)
                if install_commands
                else (
                    "Use the declared package or remote MCP target from the official "
                    "registry record."
                )
            ),
            "",
            "## Configuration",
            "Package targets: " + join_or_none(target_labels(packages)),
            "Remote targets: " + join_or_none(target_labels(remotes)),
            "",
            "## Capabilities",
            str(payload.get("description") or "Declared by the official MCP registry record."),
            "",
            "## Limitations",
            (
                "Imported from the official MCP registry. Wardn review must verify source, "
                "security, ownership, and operational claims before publication."
            ),
        ]
    )


def ensure_official_registry_documentation(payload: dict[str, Any]) -> None:
    documentation = str(payload.get("documentation") or "").strip()
    fallback = official_registry_documentation(payload)
    if not documentation:
        payload["documentation"] = fallback
        return
    if documentation_has_review_sections(documentation):
        return
    payload["documentation"] = (
        documentation + "\n\n## Wardn official registry import notes\n" + fallback
    )


def ensure_official_registry_source_review(payload: dict[str, Any], *, registry_url: str) -> None:
    meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
    source_review = meta.get("sourceReview") if isinstance(meta.get("sourceReview"), dict) else {}
    if source_review:
        return
    packages = payload.get("packages") if isinstance(payload.get("packages"), list) else []
    source_review["llm"] = {
        "filesRead": [f"Official MCP registry record: {registry_url}"],
        "installCommands": package_install_commands(packages),
        "commandArguments": package_command_arguments(packages),
        "environmentVariables": [],
        "prerequisites": [],
        "capabilitiesReviewed": True,
        "limitationsReviewed": True,
        "unknowns": [],
    }
    payload["_meta"] = {**meta, "sourceReview": source_review}


def official_github_repository(server: dict[str, Any]) -> tuple[str, str] | None:
    repository = server.get("repository")
    if not isinstance(repository, dict):
        return None
    source = str(repository.get("source") or "").strip().lower()
    url = str(repository.get("url") or "").strip()
    if source and source != "github":
        return None
    if "github.com" not in url and len([part for part in url.strip("/").split("/") if part]) < 2:
        return None
    subfolder = str(repository.get("subfolder") or "").strip()
    return url, subfolder


def source_import_payload(server: dict[str, Any]) -> dict[str, Any] | None:
    source = official_github_repository(server)
    if source is None:
        return None
    repository_url, subfolder = source
    try:
        response = import_server_source(
            ServerSourceImportRequest(repositoryUrl=repository_url, subfolder=subfolder)
        )
    except (SourceNotFoundError, UnsupportedSourceError):
        return None
    return response.server_json.model_dump(by_alias=True, exclude_none=True)


def merge_official_payload(
    *,
    official: dict[str, Any],
    imported: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = copy.deepcopy(imported) if imported is not None else copy.deepcopy(official)
    for key in (
        "$schema",
        "name",
        "title",
        "description",
        "version",
        "websiteUrl",
        "repository",
    ):
        if official.get(key):
            payload[key] = copy.deepcopy(official[key])
    for key in ("packages", "remotes", "icons"):
        if isinstance(official.get(key), list) and official[key]:
            payload[key] = copy.deepcopy(official[key])
    return payload


def build_import_payload(
    entry: dict[str, Any],
    *,
    registry_url: str,
    synced_at: datetime,
) -> dict[str, Any]:
    server = entry.get("server")
    if not isinstance(server, dict):
        raise ValueError("registry entry does not contain a server object")
    payload = merge_official_payload(official=server, imported=source_import_payload(server))

    entry_meta = entry.get("_meta") if isinstance(entry.get("_meta"), dict) else {}
    server_meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
    meta = {**copy.deepcopy(server_meta), **copy.deepcopy(entry_meta)}
    categories = metadata_categories(meta)
    if not categories:
        categories = [DEFAULT_CATEGORY]
    meta["categories"] = categories
    meta[IMPORT_META_KEY] = {
        "source": "modelcontextprotocol-registry",
        "registryUrl": registry_url,
        "syncedAt": iso_z(synced_at),
    }
    upstream_version = str(server.get("version") or "").strip()
    if upstream_version:
        meta[IMPORT_META_KEY]["upstreamVersion"] = upstream_version
    official = entry_meta.get(OFFICIAL_META_KEY)
    if isinstance(official, dict):
        meta[IMPORT_META_KEY]["upstreamStatus"] = official.get("status") or ""
        meta[IMPORT_META_KEY]["upstreamPublishedAt"] = official.get("publishedAt") or ""
        meta[IMPORT_META_KEY]["upstreamUpdatedAt"] = official.get("updatedAt") or ""
        meta[IMPORT_META_KEY]["upstreamIsLatest"] = bool(official.get("isLatest"))
    payload["_meta"] = meta
    ensure_official_registry_documentation(payload)
    ensure_official_registry_source_review(payload, registry_url=registry_url)
    return payload


def import_entry(
    hub: HubClient,
    entry: dict[str, Any],
    *,
    registry_url: str,
    synced_at: datetime,
    dry_run: bool,
    existing_submissions: dict[tuple[str, str], dict[str, Any]],
) -> ImportOutcome:
    payload = build_import_payload(entry, registry_url=registry_url, synced_at=synced_at)
    name = str(payload.get("name") or "").strip()
    version = str(payload.get("version") or "").strip()
    if not name:
        raise ValueError("server name is required")

    if official_status(entry) == "deleted":
        return ImportOutcome("skipped", "upstream_deleted")

    if dry_run:
        return ImportOutcome("candidate", "dry_run")

    try:
        server_detail = hub.get_server(name)
        upstream_version = import_upstream_version_from_payload(payload)
        published_upstream_versions = published_import_upstream_versions(server_detail)
        if upstream_version and upstream_version in published_upstream_versions:
            return ImportOutcome(
                "skipped",
                f"upstream_version_already_published={upstream_version}",
            )

        normalized_upstream_version = apply_wardn_import_version(
            payload,
            server_detail=server_detail,
        )
        version = str(payload.get("version") or "").strip()

        existing_submission = existing_submissions.get((name, version))
        if existing_submission is None:
            existing_submission = find_existing_submission_by_upstream_version(
                existing_submissions,
                name=name,
                upstream_version=upstream_version,
            )
        existing_status = (
            str(existing_submission.get("status") or "").strip()
            if existing_submission is not None
            else ""
        )
        if existing_status in {"submitted", "approved"}:
            existing_version = str(existing_submission.get("version") or "").strip()
            reason = f"pending_submission_status={existing_status}"
            if existing_version and existing_version != version:
                reason += f"; wardn_version={existing_version}; target_wardn_version={version}"
            return ImportOutcome("skipped", reason)

        submission_payload = {
            **submission_owner_fields(server_detail),
            "submissionType": "new_version" if server_detail is not None else "new_server",
            "serverJson": payload,
        }
        if existing_status in {"draft", "rejected"}:
            submission_id = str(existing_submission.get("id") or "").strip()
            if not submission_id:
                raise ValueError(f"existing {existing_status} submission missing id")
            submission = hub.update_submission(submission_id, submission_payload)
        else:
            submission = hub.create_submission(submission_payload)
    except HubApiError as exc:
        if exc.status == 409:
            return ImportOutcome("skipped", exc.detail or "already_exists")
        if exc.status in {400, 422}:
            return ImportOutcome("invalid", exc.detail or "submission_validation_failed")
        raise

    submission_id = str(submission.get("id") or "").strip()
    if not submission_id:
        raise ValueError("created submission response missing id")

    try:
        hub.submit_submission(submission_id)
    except HubApiError as exc:
        if exc.status == 400:
            return ImportOutcome("draft", exc.detail or "not_ready_for_review")
        raise
    existing_submissions[(name, version)] = {
        "id": submission_id,
        "name": name,
        "version": version,
        "status": "submitted",
    }
    if normalized_upstream_version is not None:
        return ImportOutcome(
            "submitted",
            f"submission_id={submission_id}; "
            f"wardn_version={version}; upstream_version={normalized_upstream_version}",
        )
    return ImportOutcome("submitted", f"submission_id={submission_id}")


def sync_registry(
    *,
    registry: MCPRegistryClient,
    hub: HubClient,
    registry_url: str,
    limit: int,
    version: str,
    updated_since: str | None,
    dry_run: bool,
    max_pages: int | None,
    max_records: int | None,
    verbose: bool,
) -> SyncStats:
    stats = SyncStats()
    cursor: str | None = None
    synced_at = datetime.now(UTC)
    existing_submissions = {} if dry_run else existing_submissions_by_key(hub)

    while True:
        verbose_print(
            verbose,
            "fetching registry page "
            f"{stats.pages + 1} cursor={cursor or '<initial>'} "
            f"limit={limit} version={version} updated_since={updated_since or '<none>'}",
        )
        page = registry.list_servers(
            cursor=cursor,
            limit=limit,
            version=version,
            updated_since=updated_since,
        )
        stats.pages += 1
        servers = page.get("servers")
        if not isinstance(servers, list):
            raise UserFacingError("official MCP registry response missing servers list")
        verbose_print(verbose, f"fetched page {stats.pages}: records={len(servers)}")

        for entry in servers:
            if max_records is not None and stats.seen >= max_records:
                verbose_print(verbose, f"stopping after max_records={max_records}")
                return stats
            if not isinstance(entry, dict):
                stats.invalid += 1
                verbose_print(verbose, "invalid registry entry: expected object")
                continue
            stats.seen += 1
            name, entry_version = registry_entry_identity(entry)
            try:
                outcome = import_entry(
                    hub,
                    entry,
                    registry_url=registry_url,
                    synced_at=synced_at,
                    dry_run=dry_run,
                    existing_submissions=existing_submissions,
                )
            except ValueError as exc:
                stats.invalid += 1
                if verbose:
                    print(f"invalid registry entry: {exc}", file=sys.stderr)
                continue
            except HubApiError as exc:
                if exc.status in {401, 403}:
                    raise
                stats.failed += 1
                if verbose:
                    print(f"failed to import registry entry: {exc}", file=sys.stderr)
                continue
            action = (
                f"dry-run {outcome.status}"
                if dry_run and outcome.status == "candidate"
                else outcome.status
            )
            verbose_print(
                verbose,
                f"{action}: name={name or '<missing>'} "
                f"version={entry_version or '<missing>'} reason={outcome.reason}",
            )

            if outcome.status == "candidate":
                stats.candidate += 1
            elif outcome.status == "submitted":
                stats.submitted += 1
            elif outcome.status == "draft":
                stats.draft += 1
            elif outcome.status == "invalid":
                stats.invalid += 1
            else:
                stats.skipped += 1

        metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
        next_cursor = metadata.get("nextCursor")
        cursor = next_cursor if isinstance(next_cursor, str) and next_cursor.strip() else None
        if max_records is not None and stats.seen >= max_records:
            verbose_print(verbose, f"stopping after max_records={max_records}")
            return stats
        if not cursor:
            verbose_print(verbose, "registry pagination complete")
            return stats
        if max_pages is not None and stats.pages >= max_pages:
            verbose_print(verbose, f"stopping after max_pages={max_pages}")
            return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.sync_mcp_registry",
        description=("Import official MCP registry metadata into Wardn Hub as server submissions."),
    )
    parser.add_argument(
        "--registry-url",
        default=os.getenv(REGISTRY_URL_ENV, DEFAULT_REGISTRY_URL),
        help=f"Official MCP registry list URL. Defaults to ${REGISTRY_URL_ENV}.",
    )
    parser.add_argument(
        "--url",
        "--api-base-url",
        dest="api_base_url",
        default=os.getenv(HUB_API_BASE_URL_ENV, DEFAULT_HUB_API_BASE_URL),
        help=f"Wardn Hub API base URL. Defaults to ${HUB_API_BASE_URL_ENV}.",
    )
    parser.add_argument(
        "--token",
        default="",
        help=(
            "Wardn Hub API token with submissions:read and submissions:write. "
            f"Defaults to ${HUB_TOKEN_ENV}."
        ),
    )
    parser.add_argument("--limit", type=int, default=100, help="Registry page size, max 100.")
    parser.add_argument(
        "--version",
        default="latest",
        help="Registry version filter. Use latest for daily sync or an exact version.",
    )
    parser.add_argument(
        "--updated-since",
        type=parse_datetime,
        default=None,
        help="Only fetch registry records updated since this RFC3339 timestamp.",
    )
    parser.add_argument(
        "--since-days",
        type=float,
        default=None,
        help="Only fetch records updated in the last N days.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch and validate without writes.")
    parser.add_argument("--max-pages", type=int, default=None, help="Stop after N registry pages.")
    parser.add_argument("--max-records", type=int, default=None, help="Stop after N records.")
    parser.add_argument("--http-timeout", type=float, default=30.0, help="HTTP timeout seconds.")
    parser.add_argument(
        "--registry-retries",
        type=int,
        default=DEFAULT_REGISTRY_RETRIES,
        help="Attempts for each official registry page fetch.",
    )
    parser.add_argument(
        "--registry-retry-delay",
        type=float,
        default=DEFAULT_REGISTRY_RETRY_DELAY_SECONDS,
        help="Seconds to wait between official registry fetch retries.",
    )
    parser.add_argument(
        "--user-agent",
        default=os.getenv(USER_AGENT_ENV, DEFAULT_USER_AGENT),
        help=f"HTTP User-Agent. Defaults to ${USER_AGENT_ENV}.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print page and per-record progress.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        if args.limit < 1 or args.limit > 100:
            raise UserFacingError("--limit must be between 1 and 100")
        if args.updated_since is not None and args.since_days is not None:
            raise UserFacingError("use either --updated-since or --since-days, not both")
        if args.since_days is not None and args.since_days <= 0:
            raise UserFacingError("--since-days must be greater than 0")
        if args.registry_retries < 1:
            raise UserFacingError("--registry-retries must be at least 1")
        if args.registry_retry_delay < 0:
            raise UserFacingError("--registry-retry-delay must be greater than or equal to 0")

        token = (args.token or os.getenv(HUB_TOKEN_ENV, "")).strip()
        if not token and not args.dry_run:
            raise UserFacingError(
                f"Missing Wardn Hub API token. Pass --token or set {HUB_TOKEN_ENV}."
            )

        updated_since = None
        if args.updated_since is not None:
            updated_since = iso_z(args.updated_since)
        elif args.since_days is not None:
            updated_since = iso_z(datetime.now(UTC) - timedelta(days=args.since_days))

        hub = WardnHubApiClient(
            base_url=args.api_base_url,
            token=token,
            timeout_seconds=args.http_timeout,
            user_agent=args.user_agent,
        )
        registry = MCPRegistryClient(
            registry_url=args.registry_url,
            timeout_seconds=args.http_timeout,
            user_agent=args.user_agent,
            retries=args.registry_retries,
            retry_delay_seconds=args.registry_retry_delay,
        )
        try:
            stats = sync_registry(
                registry=registry,
                hub=hub,
                registry_url=args.registry_url,
                limit=args.limit,
                version=args.version,
                updated_since=updated_since,
                dry_run=args.dry_run,
                max_pages=args.max_pages,
                max_records=args.max_records,
                verbose=args.verbose,
            )
        finally:
            registry.close()
            hub.close()
        print(
            "mcp registry sync: "
            f"pages={stats.pages} seen={stats.seen} candidate={stats.candidate} "
            f"submitted={stats.submitted} draft={stats.draft} skipped={stats.skipped} "
            f"invalid={stats.invalid} failed={stats.failed}",
            flush=True,
        )
        return 0
    except UserFacingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
