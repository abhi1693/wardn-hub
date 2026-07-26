from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

PACKAGE_REGISTRY_EVIDENCE_META_KEY = "packageRegistryEvidence"
SUPPORTED_REGISTRY_TYPES = {"npm", "pypi", "uvx"}

RegistryJsonFetcher = Callable[[str], dict[str, Any]]


def string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def registry_type_for(value: Any) -> str:
    normalized = string_value(value).casefold()
    return "pypi" if normalized == "uvx" else normalized


def package_identity(package: dict[str, Any]) -> tuple[str, str, str] | None:
    registry_type = registry_type_for(
        package.get("registryType") or package.get("registry_type")
    )
    identifier = string_value(package.get("identifier"))
    version = string_value(package.get("version"))
    if registry_type not in {"npm", "pypi"} or not identifier:
        return None
    return registry_type, identifier, version


def package_api_url(registry_type: str, identifier: str, version: str) -> str:
    encoded_identifier = quote(identifier, safe="@" if registry_type == "npm" else "")
    encoded_version = quote(version, safe="")
    if registry_type == "pypi":
        suffix = f"/{encoded_version}" if encoded_version else ""
        return f"https://pypi.org/pypi/{encoded_identifier}{suffix}/json"
    return (
        f"https://registry.npmjs.org/{encoded_identifier}/"
        f"{encoded_version or 'latest'}"
    )


def repository_url(value: Any) -> str:
    if isinstance(value, str):
        return value.removeprefix("git+").removesuffix(".git")
    if isinstance(value, dict):
        return string_value(value.get("url")).removeprefix("git+").removesuffix(".git")
    return ""


def license_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return string_value(value.get("text") or value.get("name") or value.get("type"))
    return ""


def pypi_repository(info: dict[str, Any]) -> str:
    project_urls = info.get("project_urls")
    if not isinstance(project_urls, dict):
        return ""
    normalized = {
        str(key).strip().casefold(): string_value(value)
        for key, value in project_urls.items()
    }
    for key in ("source", "source code", "repository", "code", "github"):
        if normalized.get(key):
            return normalized[key]
    return ""


def pypi_evidence(
    *,
    identifier: str,
    requested_version: str,
    api_url: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    info_value = payload.get("info")
    info = info_value if isinstance(info_value, dict) else {}
    resolved_version = string_value(info.get("version"))
    status = "published" if resolved_version else "metadata_invalid"
    if requested_version and resolved_version and requested_version != resolved_version:
        status = "version_mismatch"

    project_urls = info.get("project_urls")
    project_url_values = (
        {
            str(key): string_value(value)
            for key, value in project_urls.items()
            if string_value(value)
        }
        if isinstance(project_urls, dict)
        else {}
    )
    raw_uploads = payload.get("urls")
    uploads = [
        value
        for value in (raw_uploads if isinstance(raw_uploads, list) else [])
        if isinstance(value, dict)
    ]
    raw_dependencies = info.get("requires_dist")
    dependencies = raw_dependencies if isinstance(raw_dependencies, list) else []
    published_at = min(
        (
            string_value(upload.get("upload_time_iso_8601"))
            for upload in uploads
            if string_value(upload.get("upload_time_iso_8601"))
        ),
        default="",
    )
    sha256 = next(
        (
            string_value(digests.get("sha256"))
            for upload in uploads
            if isinstance((digests := upload.get("digests")), dict)
            and string_value(digests.get("sha256"))
        ),
        "",
    )
    return {
        "registryType": "pypi",
        "identifier": identifier,
        "requestedVersion": requested_version,
        "resolvedVersion": resolved_version,
        "status": status,
        "registryApiUrl": api_url,
        "packageUrl": string_value(info.get("package_url"))
        or f"https://pypi.org/project/{quote(identifier, safe='')}/",
        "summary": string_value(info.get("summary")),
        "license": license_value(info.get("license")),
        "homepage": string_value(info.get("home_page")),
        "repository": pypi_repository(info),
        "projectUrls": project_url_values,
        "requiresPython": string_value(info.get("requires_python")),
        "dependencies": [
            string_value(value)
            for value in dependencies
            if string_value(value)
        ][:100],
        "publishedAt": published_at,
        "sha256": sha256,
        "authoritativeFor": ["identifier", "version", "publication"],
        "contextOnly": [
            "summary",
            "license",
            "homepage",
            "repository",
            "projectUrls",
            "requiresPython",
            "dependencies",
        ],
    }


def npm_evidence(
    *,
    identifier: str,
    requested_version: str,
    api_url: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    resolved_version = string_value(payload.get("version"))
    status = "published" if resolved_version else "metadata_invalid"
    if requested_version and resolved_version and requested_version != resolved_version:
        status = "version_mismatch"

    dist_value = payload.get("dist")
    dist = dist_value if isinstance(dist_value, dict) else {}
    engines_value = payload.get("engines")
    engines = engines_value if isinstance(engines_value, dict) else {}
    bin_value = payload.get("bin")
    binaries = bin_value if isinstance(bin_value, dict) else {}
    return {
        "registryType": "npm",
        "identifier": identifier,
        "requestedVersion": requested_version,
        "resolvedVersion": resolved_version,
        "status": status,
        "registryApiUrl": api_url,
        "packageUrl": f"https://www.npmjs.com/package/{quote(identifier, safe='@/')}",
        "summary": string_value(payload.get("description")),
        "license": license_value(payload.get("license")),
        "homepage": string_value(payload.get("homepage")),
        "repository": repository_url(payload.get("repository")),
        "engines": {
            str(key): string_value(value)
            for key, value in engines.items()
            if string_value(value)
        },
        "binaries": {
            str(key): string_value(value)
            for key, value in binaries.items()
            if string_value(value)
        },
        "deprecated": string_value(payload.get("deprecated")),
        "integrity": string_value(dist.get("integrity")),
        "shasum": string_value(dist.get("shasum")),
        "authoritativeFor": ["identifier", "version", "publication"],
        "contextOnly": [
            "summary",
            "license",
            "homepage",
            "repository",
            "engines",
            "binaries",
            "deprecated",
        ],
    }


def package_registry_evidence(
    package: dict[str, Any],
    *,
    fetch_json: RegistryJsonFetcher,
) -> dict[str, Any] | None:
    identity = package_identity(package)
    if identity is None:
        return None
    registry_type, identifier, requested_version = identity
    api_url = package_api_url(registry_type, identifier, requested_version)
    try:
        payload = fetch_json(api_url)
    except Exception:
        return {
            "registryType": registry_type,
            "identifier": identifier,
            "requestedVersion": requested_version,
            "resolvedVersion": "",
            "status": "unavailable",
            "registryApiUrl": api_url,
            "authoritativeFor": ["identifier", "version", "publication"],
            "contextOnly": [],
        }
    if not payload:
        return {
            "registryType": registry_type,
            "identifier": identifier,
            "requestedVersion": requested_version,
            "resolvedVersion": "",
            "status": "not_found",
            "registryApiUrl": api_url,
            "authoritativeFor": ["identifier", "version", "publication"],
            "contextOnly": [],
        }
    if registry_type == "pypi":
        return pypi_evidence(
            identifier=identifier,
            requested_version=requested_version,
            api_url=api_url,
            payload=payload,
        )
    return npm_evidence(
        identifier=identifier,
        requested_version=requested_version,
        api_url=api_url,
        payload=payload,
    )


def add_package_registry_evidence(
    server_json: dict[str, Any],
    *,
    fetch_json: RegistryJsonFetcher,
) -> dict[str, Any]:
    packages = server_json.get("packages")
    if not isinstance(packages, list):
        return server_json
    evidence = [
        result
        for package in packages
        if isinstance(package, dict)
        and (result := package_registry_evidence(package, fetch_json=fetch_json)) is not None
    ]
    if not evidence:
        return server_json
    meta_value = server_json.get("_meta")
    meta = meta_value if isinstance(meta_value, dict) else {}
    return {
        **server_json,
        "_meta": {
            **meta,
            PACKAGE_REGISTRY_EVIDENCE_META_KEY: evidence,
        },
    }
