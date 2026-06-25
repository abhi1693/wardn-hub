import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from app.modules.imports.exceptions import SourceNotFoundError, UnsupportedSourceError
from app.modules.imports.schemas import ServerSourceImportRequest, ServerSourceImportResponse

DEFAULT_SCHEMA = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
GITHUB_HOST = "github.com"
MAX_IMPORT_BYTES = 512_000
FENCED_CODE_PATTERN = re.compile(r"```(?:json|jsonc)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class GitHubRepository:
    owner: str
    repo: str


def string_value(value: Any) -> str:
    return value if isinstance(value, str) else ""


def dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def strip_git_suffix(value: str) -> str:
    return value.strip().removesuffix(".git")


def parse_github_repository(value: str) -> GitHubRepository:
    raw_value = value.strip()
    raw_path_parts = [part for part in raw_value.strip("/").split("/") if part]
    if "://" not in raw_value and "@" not in raw_value and len(raw_path_parts) >= 2:
        return GitHubRepository(owner=raw_path_parts[0], repo=strip_git_suffix(raw_path_parts[1]))

    ssh_parts = raw_value.replace("ssh://git@", "git@")
    if ssh_parts.startswith("git@"):
        host_and_path = ssh_parts.removeprefix("git@")
        host, _, path = host_and_path.partition(":")
        path_parts = [part for part in path.split("/") if part]
        if host.lower().replace("www.", "") == GITHUB_HOST and len(path_parts) >= 2:
            return GitHubRepository(owner=path_parts[0], repo=strip_git_suffix(path_parts[1]))

    try:
        url = urlparse(raw_value if "://" in raw_value else f"https://{raw_value}")
    except ValueError as exc:
        raise UnsupportedSourceError(
            "source import currently supports GitHub repositories"
        ) from exc

    if url.hostname is None or url.hostname.lower().replace("www.", "") != GITHUB_HOST:
        raise UnsupportedSourceError("source import currently supports GitHub repositories")

    path_parts = [part for part in url.path.split("/") if part]
    if len(path_parts) < 2:
        raise UnsupportedSourceError("repositoryUrl must include GitHub owner and repository")

    return GitHubRepository(owner=path_parts[0], repo=strip_git_suffix(path_parts[1]))


def repository_reference(repository: GitHubRepository) -> str:
    return f"{repository.owner}/{repository.repo}"


def repository_web_url(repository: GitHubRepository) -> str:
    return f"https://{GITHUB_HOST}/{repository.owner}/{repository.repo}"


def clean_subfolder(value: str) -> str:
    return value.strip().strip("/")


def fetch_text(url: str, *, accept: str = "application/json") -> str | None:
    request = Request(url, headers={"Accept": accept, "User-Agent": "wardn-hub-importer/0.1"})
    try:
        with urlopen(request, timeout=10) as response:
            data = response.read(MAX_IMPORT_BYTES + 1)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise SourceNotFoundError("source metadata could not be loaded") from exc
    except URLError as exc:
        raise SourceNotFoundError("source metadata could not be loaded") from exc

    if len(data) > MAX_IMPORT_BYTES:
        raise SourceNotFoundError("source metadata is too large to import")
    return data.decode("utf-8", errors="replace")


def fetch_json(url: str) -> dict[str, Any]:
    text = fetch_text(url)
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def github_api_url(repository: GitHubRepository, path: str) -> str:
    return (
        "https://api.github.com/repos/"
        f"{quote(repository.owner, safe='')}/{quote(repository.repo, safe='')}{path}"
    )


def github_raw_url(repository: GitHubRepository, branch: str, path: str) -> str:
    return (
        f"https://raw.githubusercontent.com/{quote(repository.owner, safe='')}/"
        f"{quote(repository.repo, safe='')}/{quote(branch, safe='')}/{path}"
    )


def fetch_github_metadata(repository: GitHubRepository) -> dict[str, str]:
    payload = fetch_json(github_api_url(repository, ""))
    homepage = string_value(payload.get("homepage"))
    html_url = string_value(payload.get("html_url"))
    owner = payload.get("owner") if isinstance(payload.get("owner"), dict) else {}
    return {
        "title": string_value(payload.get("name")),
        "description": string_value(payload.get("description")),
        "iconUrl": string_value(owner.get("avatar_url")),
        "websiteUrl": homepage or html_url,
    }


def fetch_github_readme(repository: GitHubRepository, subfolder: str) -> str:
    readme_path = f"/{clean_subfolder(subfolder)}" if clean_subfolder(subfolder) else ""
    text = fetch_text(
        github_api_url(repository, f"/readme{readme_path}"),
        accept="application/vnd.github.raw",
    )
    return text or ""


def raw_metadata_candidates(repository: GitHubRepository, subfolder: str) -> list[tuple[str, str]]:
    folder = clean_subfolder(subfolder)
    paths = ["server.json", "mcp.json"]
    branches = ["main", "master"]
    candidates = []
    for branch in branches:
        for path in paths:
            file_path = "/".join(part for part in (folder, path) if part)
            candidates.append((path, github_raw_url(repository, branch, file_path)))
    return candidates


def metadata_from_mcp_json(value: dict[str, Any], repository: GitHubRepository) -> dict[str, Any]:
    servers = value.get("mcpServers") if isinstance(value.get("mcpServers"), dict) else {}
    server_title, raw_config = next(iter(servers.items()), ("", {}))
    config = raw_config if isinstance(raw_config, dict) else {}
    url = string_value(config.get("url"))
    command = string_value(config.get("command"))
    args = (
        [str(argument) for argument in config.get("args", [])]
        if isinstance(config.get("args"), list)
        else []
    )
    env = config.get("env") if isinstance(config.get("env"), dict) else {}
    package_identifier = next((argument for argument in args if not argument.startswith("-")), "")

    return {
        "source": "mcp.json",
        "title": server_title,
        "version": "1.0.0",
        "websiteUrl": repository_web_url(repository),
        "repository": {
            "source": "github",
            "url": repository_reference(repository),
        },
        "remotes": [{"type": "streamable-http", "url": url}] if url else [],
        "packages": [
            {
                "registryType": "uvx" if "uv" in command else "npm",
                "identifier": package_identifier,
                "transport": {
                    "type": "stdio",
                    "command": command,
                    "args": args,
                    "env": env,
                },
            }
        ]
        if command and package_identifier
        else [],
    }


def strip_json_comments(value: str) -> str:
    without_block_comments = re.sub(r"/\*.*?\*/", "", value, flags=re.DOTALL)
    without_line_comments = re.sub(r"(?m)^\s*//.*$", "", without_block_comments)
    return re.sub(r",(\s*[}\]])", r"\1", without_line_comments)


def extract_readme_mcp_json(readme: str) -> dict[str, Any]:
    if "mcpServers" not in readme:
        return {}

    for match in FENCED_CODE_PATTERN.finditer(readme):
        snippet = match.group(1).strip()
        if "mcpServers" not in snippet:
            continue
        try:
            value = json.loads(strip_json_comments(snippet))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("mcpServers"), dict):
            return value

    return {}


def merge_readme_package_config(
    server_json: dict[str, Any],
    readme_metadata: dict[str, Any],
) -> dict[str, Any]:
    readme_packages = dict_items(readme_metadata.get("packages"))
    if not readme_packages:
        return server_json

    packages = dict_items(server_json.get("packages"))
    if not packages:
        return {**server_json, "packages": readme_packages}

    readme_package = readme_packages[0]
    readme_transport = readme_package.get("transport")
    readme_transport_value = readme_transport if isinstance(readme_transport, dict) else {}
    readme_identifier = string_value(readme_package.get("identifier"))
    merged_packages: list[dict[str, Any]] = []

    for package in packages:
        package_identifier = string_value(package.get("identifier"))
        should_merge = (
            len(packages) == 1
            or not readme_identifier
            or package_identifier == readme_identifier
        )
        if not should_merge:
            merged_packages.append(package)
            continue

        transport = package.get("transport")
        transport_value = transport if isinstance(transport, dict) else {}
        merged_transport = {
            **readme_transport_value,
            **transport_value,
        }
        for key in ("command", "args", "env", "type"):
            if not merged_transport.get(key) and readme_transport_value.get(key):
                merged_transport[key] = readme_transport_value[key]
        merged_packages.append(
            {
                **readme_package,
                **package,
                "transport": merged_transport,
            }
        )

    return {**server_json, "packages": merged_packages}


def import_missing_fields(server_json: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not dict_items(server_json.get("packages")) and not dict_items(server_json.get("remotes")):
        missing.append("packages or remotes")

    for package in dict_items(server_json.get("packages")):
        registry_type = string_value(package.get("registryType")).lower()
        if registry_type == "mcpb":
            continue
        transport = package.get("transport")
        transport_value = transport if isinstance(transport, dict) else {}
        transport_type = string_value(transport_value.get("type")).lower()
        if transport_type and transport_type not in {"stdio", "local"}:
            continue
        if not string_value(transport_value.get("command")):
            missing.append("package transport command")
        if not transport_value.get("args"):
            missing.append("package transport args")

    meta = server_json.get("_meta") if isinstance(server_json.get("_meta"), dict) else {}
    source_review = meta.get("sourceReview") if isinstance(meta.get("sourceReview"), dict) else {}
    if not source_review:
        missing.append("source review evidence")

    return list(dict.fromkeys(missing))


def with_server_targets(metadata: dict[str, Any], server_json: dict[str, Any]) -> dict[str, Any]:
    return {
        **metadata,
        "packages": dict_items(server_json.get("packages")),
        "remotes": dict_items(server_json.get("remotes")),
        "icons": dict_items(server_json.get("icons")),
    }


def with_fallback(metadata: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    return {
        **metadata,
        "title": string_value(metadata.get("title")) or string_value(fallback.get("title")),
        "description": string_value(metadata.get("description"))
        or string_value(fallback.get("description")),
        "documentation": string_value(metadata.get("documentation"))
        or string_value(fallback.get("documentation")),
        "iconUrl": string_value(metadata.get("iconUrl")) or string_value(fallback.get("iconUrl")),
        "websiteUrl": string_value(metadata.get("websiteUrl"))
        or string_value(fallback.get("websiteUrl")),
    }


def server_json_from_metadata(
    metadata: dict[str, Any],
    repository: GitHubRepository,
    subfolder: str,
) -> dict[str, Any]:
    repository_payload = metadata.get("repository")
    repository_value = repository_payload if isinstance(repository_payload, dict) else {}
    packages = dict_items(metadata.get("packages"))
    remotes = dict_items(metadata.get("remotes"))
    icons = dict_items(metadata.get("icons"))
    icon_url = string_value(metadata.get("iconUrl"))
    if icon_url and not icons:
        icons = [{"src": icon_url}]

    return {
        "$schema": string_value(metadata.get("$schema")) or DEFAULT_SCHEMA,
        "name": string_value(metadata.get("name")),
        "title": string_value(metadata.get("title")),
        "description": string_value(metadata.get("description")),
        "documentation": string_value(metadata.get("documentation")),
        "repository": {
            "source": string_value(repository_value.get("source")) or "github",
            "url": string_value(repository_value.get("url")) or repository_reference(repository),
            **({"subfolder": subfolder} if subfolder else {}),
        },
        "version": string_value(metadata.get("version")) or "1.0.0",
        "websiteUrl": string_value(metadata.get("websiteUrl")) or repository_web_url(repository),
        "icons": icons,
        "packages": packages,
        "remotes": remotes,
    }


def import_server_source(payload: ServerSourceImportRequest) -> ServerSourceImportResponse:
    repository = parse_github_repository(payload.repository_url)
    subfolder = clean_subfolder(payload.subfolder)
    metadata = fetch_github_metadata(repository)
    readme = fetch_github_readme(repository, subfolder)
    fallback = {**metadata, "documentation": readme}
    files = ["README.md"] if readme else []
    readme_mcp_json = extract_readme_mcp_json(readme)
    readme_mcp_metadata = (
        metadata_from_mcp_json(readme_mcp_json, repository) if readme_mcp_json else {}
    )

    for path, candidate_url in raw_metadata_candidates(repository, subfolder):
        text = fetch_text(candidate_url)
        if not text:
            continue
        try:
            raw_payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw_payload, dict):
            continue
        files.append(path)

        if raw_payload.get("$schema") or raw_payload.get("packages") or raw_payload.get("remotes"):
            metadata = with_fallback(
                {
                    **raw_payload,
                    "source": "server.json",
                    "repository": {
                        "source": "github",
                        "url": repository_reference(repository),
                        **({"subfolder": subfolder} if subfolder else {}),
                    },
                },
                fallback,
            )
            server_json = server_json_from_metadata(metadata, repository, subfolder)
            server_json = merge_readme_package_config(server_json, readme_mcp_metadata)
            metadata = with_server_targets(metadata, server_json)
            return ServerSourceImportResponse(
                **metadata,
                serverJson=server_json,
                submissionPayload={"submissionType": "new_server", "serverJson": server_json},
                evidence={"files": files, "missing": import_missing_fields(server_json)},
            )

        if raw_payload.get("mcpServers"):
            metadata = with_fallback(metadata_from_mcp_json(raw_payload, repository), fallback)
            server_json = server_json_from_metadata(metadata, repository, subfolder)
            metadata = with_server_targets(metadata, server_json)
            return ServerSourceImportResponse(
                **metadata,
                serverJson=server_json,
                submissionPayload={"submissionType": "new_server", "serverJson": server_json},
                evidence={"files": files, "missing": import_missing_fields(server_json)},
            )

    if readme_mcp_json:
        metadata = with_fallback(readme_mcp_metadata, fallback)
        server_json = server_json_from_metadata(metadata, repository, subfolder)
        metadata = with_server_targets(metadata, server_json)
        return ServerSourceImportResponse(
            **metadata,
            serverJson=server_json,
            submissionPayload={"submissionType": "new_server", "serverJson": server_json},
            evidence={"files": files, "missing": import_missing_fields(server_json)},
        )

    server_json = server_json_from_metadata(
        {
            **fallback,
            "source": "github",
            "repository": {
                "source": "github",
                "url": repository_reference(repository),
                **({"subfolder": subfolder} if subfolder else {}),
            },
        },
        repository,
        subfolder,
    )
    missing = import_missing_fields(server_json)
    return ServerSourceImportResponse(
        source="github",
        title=string_value(fallback.get("title")),
        description=string_value(fallback.get("description")),
        documentation=readme,
        websiteUrl=string_value(fallback.get("websiteUrl")),
        iconUrl=string_value(fallback.get("iconUrl")),
        repository=server_json["repository"],
        serverJson=server_json,
        submissionPayload={"submissionType": "new_server", "serverJson": server_json},
        evidence={"files": files, "missing": missing},
    )
