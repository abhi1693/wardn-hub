from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Literal, NotRequired, TypedDict
from urllib.parse import quote, urlparse

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.modules.skills.models import Skill, SkillAudit, SkillSnapshot, SkillSourceOwner

logger = logging.getLogger(__name__)

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
GITHUB_OWNER_PATTERN = re.compile(
    r"^(?!.*--)[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$"
)
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
GITHUB_API_ROOT = "https://api.github.com"
GITHUB_REPOSITORIES_PER_PAGE = 100
GITHUB_SEARCH_RESULT_LIMIT = 1000
GITHUB_VERIFIED_ORG_CACHE_SIZE = 1024
GITHUB_CREATED_AT_FLOOR = datetime(1970, 1, 1, tzinfo=UTC)
GITHUB_RATE_LIMIT_WAIT_BUFFER_SECONDS = 1.0
GITHUB_SECONDARY_RATE_LIMIT_WAIT_SECONDS = 60.0
GITHUB_SECONDARY_RATE_LIMIT_MAX_WAIT_SECONDS = 15 * 60.0
GITHUB_TRANSIENT_RETRY_BASE_SECONDS = 1.0
GITHUB_TRANSIENT_RETRY_MAX_SECONDS = 8.0
GITHUB_TRANSIENT_MAX_RETRIES = 3
GITHUB_ERROR_BODY_MAX_CHARS = 1000
DEFAULT_USER_AGENT = "WardnHubSkillsImporter/0.1"
DEFAULT_IMPORT_TIMEOUT_SECONDS = 20.0
MAX_LOGGED_SKILL_PATHS = 20
MAX_SKILL_BUNDLE_FILES = 256
MAX_SKILL_FILE_BYTES = 8 * 1024 * 1024
MAX_SKILL_BUNDLE_BYTES = 16 * 1024 * 1024
MAX_BUNDLE_FETCH_CONCURRENCY = 8
MAX_GITHUB_IMPORT_BYTES = 256 * 1024 * 1024
SKIPPED_PATH_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "vendor",
}


class SkillCliError(Exception):
    pass


class GitHubSystemicError(SkillCliError):
    pass


class SkillNotFoundError(SkillCliError):
    pass


class GitHubTreeTruncatedError(SkillCliError):
    pass


class InvalidSkillTextError(SkillCliError):
    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{reason}: {path}")


class InvalidSkillBundleError(SkillCliError):
    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{reason}: {path}")


SkillFileEncoding = Literal["utf-8", "base64"]


class SkillSnapshotFile(TypedDict):
    path: str
    contents: str
    encoding: NotRequired[SkillFileEncoding]
    executable: NotRequired[bool]


@dataclass(frozen=True)
class SkillAddInput:
    source: str
    source_owner: str
    source_name: str
    source_owner_url: str
    source_owner_icon_url: str
    source_url: str
    slug: str
    name: str
    description: str
    skill_md: str
    files: list[SkillSnapshotFile]
    source_type: str = "github"
    install_url: str = ""
    website_url: str = ""
    repository_url: str = ""
    repository_subfolder: str = ""
    repository_ref: str = ""


@dataclass(frozen=True)
class GitHubRepository:
    owner: str
    repo: str
    url: str
    path: str = ""
    ref: str = ""

    @property
    def source(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class GitHubTreeItem:
    path: str
    type: str
    size: int = 0
    mode: str = "100644"


@dataclass(frozen=True)
class GitHubRepositoryMetadata:
    default_branch: str
    owner_avatar_url: str
    fork: bool = False
    archived: bool = False
    disabled: bool = False


@dataclass(frozen=True)
class GitHubOwner:
    login: str
    account_type: Literal["User", "Organization"]
    avatar_url: str


@dataclass(frozen=True)
class GitHubImportRepository:
    repo: GitHubRepository
    default_branch: str
    owner_avatar_url: str = ""


@dataclass(frozen=True)
class GitHubRepositoryListing:
    owner: GitHubOwner
    repositories: list[GitHubImportRepository]
    listed_count: int


@dataclass(frozen=True)
class GitHubRepositoryFilters:
    legacy_owners: tuple[str, ...] = ()
    organizations: tuple[str, ...] = ()
    users: tuple[str, ...] = ()
    repositories: tuple[str, ...] = ()
    all_github: bool = False
    min_stars: int | None = None
    max_stars: int | None = None
    pushed_after: str = ""
    pushed_before: str = ""
    created_after: str = ""
    created_before: str = ""
    language: str = ""
    topics: tuple[str, ...] = ()
    verified_orgs_only: bool = False
    max_repositories: int | None = None

    @property
    def scope_label(self) -> str:
        if self.all_github:
            return "all GitHub"
        targets = [
            *self.legacy_owners,
            *(f"org:{owner}" for owner in self.organizations),
            *(f"user:{owner}" for owner in self.users),
            *(f"repo:{repository}" for repository in self.repositories),
        ]
        return ", ".join(targets)


@dataclass
class GitHubDiscoveryStats:
    scope_label: str
    search_query_count: int = 0
    listed_repository_count: int = 0
    active_repository_count: int = 0
    filtered_repository_count: int = 0
    known_repository_count: int | None = None


@dataclass(frozen=True)
class GitHubRepositorySearchPage:
    total_count: int
    incomplete_results: bool
    items: list[dict[str, object]]


@dataclass(frozen=True)
class GitHubSearchTarget:
    qualifier: str
    value: str
    avatar_url: str = ""


@dataclass
class GitHubSearchBudget:
    remaining: int | None
    exhausted: bool = False

    def consume(self) -> bool:
        if self.remaining is None:
            return True
        if self.remaining <= 0:
            self.exhausted = True
            return False
        self.remaining -= 1
        self.exhausted = self.remaining == 0
        return True


@dataclass(frozen=True)
class ImportedSkill:
    payload: SkillAddInput
    source_path: str
    bundle_size: int


@dataclass(frozen=True)
class SkillRefreshTarget:
    skill_id: object
    current_snapshot_id: object | None
    current_hash: str | None
    source: str
    slug: str
    repository: dict[str, object]
    repo: GitHubRepository
    subfolder: str
    ref: str

    @property
    def id(self) -> str:
        return f"{self.source}/{self.slug}"

    @property
    def skill_path(self) -> str:
        return f"{self.subfolder}/SKILL.md" if self.subfolder else "SKILL.md"


@dataclass(frozen=True)
class SkillRefreshIssue:
    skill_id: str
    reason: str


@dataclass(frozen=True)
class GitHubRateLimitWait:
    seconds: float
    reason: Literal["primary", "secondary"]


def github_http_error(status_code: int, message: str) -> SkillCliError:
    if status_code in {401, 403, 429} or status_code >= 500:
        return GitHubSystemicError(message)
    return SkillCliError(message)


def github_response_error_message(response: object, operation: str) -> str:
    status_code = getattr(response, "status_code", "unknown")
    request_id = github_response_header(response, "x-github-request-id")
    details = f"HTTP {status_code}"
    if request_id:
        details = f"{details}, request ID {request_id}"

    body = str(getattr(response, "text", "") or "").strip()
    if len(body) > GITHUB_ERROR_BODY_MAX_CHARS:
        body = f"{body[:GITHUB_ERROR_BODY_MAX_CHARS]}..."
    return f"{operation} ({details}): {body or 'empty response body'}"


def github_response_header(response: object, name: str) -> str:
    headers = getattr(response, "headers", {})
    if not hasattr(headers, "get"):
        return ""
    value = headers.get(name, "")
    return str(value).strip()


def github_rate_limit_response_text(response: object) -> str:
    text = str(getattr(response, "text", "") or "")
    try:
        payload = response.json()  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        return text.casefold()
    if isinstance(payload, dict):
        message = payload.get("message")
        documentation_url = payload.get("documentation_url")
        values = [text]
        if isinstance(message, str):
            values.append(message)
        if isinstance(documentation_url, str):
            values.append(documentation_url)
        return " ".join(values).casefold()
    return text.casefold()


def github_rate_limit_wait(
    response: object,
    *,
    retry_attempt: int,
    now_epoch_seconds: float,
) -> GitHubRateLimitWait | None:
    status_code = getattr(response, "status_code", None)
    if status_code not in {403, 429}:
        return None

    retry_after = github_response_header(response, "retry-after")
    if retry_after:
        try:
            retry_after_seconds = float(retry_after)
        except ValueError:
            retry_after_seconds = -1
        if retry_after_seconds >= 0:
            return GitHubRateLimitWait(
                seconds=retry_after_seconds + GITHUB_RATE_LIMIT_WAIT_BUFFER_SECONDS,
                reason="secondary",
            )

    remaining = github_response_header(response, "x-ratelimit-remaining")
    reset = github_response_header(response, "x-ratelimit-reset")
    if remaining == "0":
        try:
            reset_epoch_seconds = float(reset)
        except ValueError:
            reset_epoch_seconds = now_epoch_seconds + GITHUB_SECONDARY_RATE_LIMIT_WAIT_SECONDS
        return GitHubRateLimitWait(
            seconds=max(0.0, reset_epoch_seconds - now_epoch_seconds)
            + GITHUB_RATE_LIMIT_WAIT_BUFFER_SECONDS,
            reason="primary",
        )

    response_text = github_rate_limit_response_text(response)
    is_secondary = status_code == 429 or any(
        marker in response_text
        for marker in (
            "secondary rate limit",
            "abuse detection",
            "rate limit exceeded",
            "rate-limits-for-the-rest-api",
        )
    )
    if not is_secondary:
        return None
    exponential_wait = GITHUB_SECONDARY_RATE_LIMIT_WAIT_SECONDS * (
        2 ** min(retry_attempt, 4)
    )
    return GitHubRateLimitWait(
        seconds=min(exponential_wait, GITHUB_SECONDARY_RATE_LIMIT_MAX_WAIT_SECONDS),
        reason="secondary",
    )


def github_transient_retry_wait(retry_attempt: int) -> float:
    return min(
        GITHUB_TRANSIENT_RETRY_BASE_SECONDS * (2**retry_attempt),
        GITHUB_TRANSIENT_RETRY_MAX_SECONDS,
    )


def github_json(response: object, description: str) -> object:
    try:
        return response.json()  # type: ignore[attr-defined]
    except ValueError as exc:
        raise GitHubSystemicError(f"GitHub returned malformed {description} JSON") from exc


async def validate_github_request(request: httpx.Request) -> None:
    if request.url.scheme != "https" or request.url.host not in {
        "api.github.com",
        "raw.githubusercontent.com",
    }:
        raise GitHubSystemicError(f"refusing unsafe GitHub request URL: {request.url.host}")


def unsupported_text_control(contents: str) -> tuple[int, str] | None:
    for offset, character in enumerate(contents):
        codepoint = ord(character)
        if (codepoint < 32 and character not in "\t\n\r") or 127 <= codepoint <= 159:
            return offset, character
    return None


def checked_github_import_size(current_size: int, bundle_size: int) -> int:
    total_size = current_size + bundle_size
    if total_size > MAX_GITHUB_IMPORT_BYTES:
        raise SkillCliError(
            f"GitHub repository import exceeds {MAX_GITHUB_IMPORT_BYTES} bytes; "
            "choose a narrower --subfolder"
        )
    return total_size


def github_token_from_args(args: argparse.Namespace) -> str:
    explicit_token = str(getattr(args, "github_token", "") or "").strip()
    return explicit_token or os.getenv(GITHUB_TOKEN_ENV, "").strip()


def parse_frontmatter(contents: str) -> dict[str, str]:
    lines = contents.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    metadata: dict[str, str] = {}
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            return metadata
        key, separator, value = stripped.partition(":")
        if not separator or not key.strip():
            continue
        metadata[key.strip()] = value.strip().strip("\"'")
    return {}


def slug_from_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "skill"


def slug_from_skill_root(root: str, fallback: str) -> str:
    return slug_from_name(root or fallback)


def skill_slug_root(root: str, import_subfolder: str) -> str:
    if not import_subfolder:
        return root
    if root == import_subfolder:
        return Path(root).name
    prefix = f"{import_subfolder}/"
    if root.startswith(prefix):
        return str(Path(root).relative_to(import_subfolder))
    return root


def validate_skill_source(source: str, *, source_type: str = "github") -> str:
    normalized = source.strip().strip("/")
    if not normalized:
        raise SkillCliError("--source is required")
    if source_type == "github" and "/" not in normalized:
        raise SkillCliError("--source must look like owner/repo for GitHub skills")
    return normalized


def source_owner_from_source(source: str) -> str:
    return source.split("/", 1)[0] if "/" in source else source


def source_name_from_source(source: str) -> str:
    return source.split("/", 1)[1] if "/" in source else source


def github_owner_url(owner: str) -> str:
    return f"https://github.com/{owner}"


def github_source_url(source: str) -> str:
    return f"https://github.com/{source}"


def validate_skill_owner(owner: str) -> str:
    normalized = owner.strip().strip("/")
    if not normalized or "/" in normalized:
        raise SkillCliError("owner must look like a GitHub owner, for example vercel-labs")
    return normalized


def validate_github_owner(owner: str) -> str:
    normalized = owner.strip()
    if not GITHUB_OWNER_PATTERN.fullmatch(normalized):
        raise SkillCliError(
            "owner must be a bare GitHub user or organization login, for example vercel-labs"
        )
    return normalized


def github_owner_argument(value: str) -> str:
    try:
        return validate_github_owner(value)
    except SkillCliError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def github_repository_argument(value: str) -> str:
    normalized = value.strip().strip("/")
    parts = normalized.split("/")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            "repository must look like owner/repo, for example anthropics/skills"
        )
    try:
        owner = validate_github_owner(parts[0])
    except SkillCliError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    repository = parts[1].removesuffix(".git")
    if (
        not repository
        or len(repository) > 100
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", repository)
    ):
        raise argparse.ArgumentTypeError(
            "repository name may contain letters, numbers, dots, hyphens, and underscores"
        )
    return f"{owner}/{repository}"


def github_timestamp_argument(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise argparse.ArgumentTypeError("timestamp must not be empty")
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "timestamp must be an ISO-8601 date or datetime, for example 2026-01-31"
        ) from exc
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
        return normalized
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def github_language_argument(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 100 or '"' in normalized:
        raise argparse.ArgumentTypeError("language must be a nonempty GitHub language name")
    return normalized


def github_topic_argument(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized) or len(normalized) > 50:
        raise argparse.ArgumentTypeError(
            "topic must contain lowercase letters, numbers, and single hyphens"
        )
    return normalized


def nonnegative_int_argument(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def positive_int_argument(value: str) -> int:
    parsed = nonnegative_int_argument(value)
    if parsed == 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def import_subfolder_argument(value: str) -> str:
    try:
        return validate_import_subfolder(value)
    except SkillCliError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def unique_casefolded(values: list[str]) -> tuple[str, ...]:
    unique: dict[str, str] = {}
    for value in values:
        unique.setdefault(value.casefold(), value)
    return tuple(unique.values())


def github_repository_filters_from_args(args: argparse.Namespace) -> GitHubRepositoryFilters:
    positional_owner = str(getattr(args, "owner", "") or "").strip()
    generic_owners = list(getattr(args, "owners", []) or [])
    legacy_owners = unique_casefolded(
        [
            *(validate_github_owner(owner) for owner in generic_owners),
            *([validate_github_owner(positional_owner)] if positional_owner else []),
        ]
    )
    organizations = unique_casefolded(
        [validate_github_owner(owner) for owner in (getattr(args, "organizations", []) or [])]
    )
    users = unique_casefolded(
        [validate_github_owner(owner) for owner in (getattr(args, "users", []) or [])]
    )
    raw_repositories = list(getattr(args, "repositories", []) or [])
    repositories = unique_casefolded(
        [github_repository_argument(repository) for repository in raw_repositories]
    )
    all_github = bool(getattr(args, "all_github", False))
    if all_github and (legacy_owners or organizations or users or repositories):
        raise SkillCliError(
            "--all-github cannot be combined with owner, org, user, or repo targets"
        )
    if not all_github and not (legacy_owners or organizations or users or repositories):
        raise SkillCliError(
            "choose a GitHub target: OWNER, --owner, --org, --user, --repo, or --all-github"
        )

    min_stars = getattr(args, "min_stars", None)
    max_stars = getattr(args, "max_stars", None)
    if min_stars is not None and max_stars is not None and min_stars > max_stars:
        raise SkillCliError("--min-stars cannot be greater than --max-stars")

    created_after = str(getattr(args, "created_after", "") or "")
    created_before = str(getattr(args, "created_before", "") or "")
    if created_after and created_before:
        after = parse_github_datetime(created_after, upper_bound=False)
        before = parse_github_datetime(created_before, upper_bound=True)
        if after > before:
            raise SkillCliError("--created-after cannot be later than --created-before")

    pushed_after = str(getattr(args, "pushed_after", "") or "")
    active_within_days = getattr(args, "active_within_days", None)
    if pushed_after and active_within_days is not None:
        raise SkillCliError("--active-within-days cannot be combined with --pushed-after")
    if active_within_days is not None:
        pushed_after = (
            datetime.now(tz=UTC) - timedelta(days=active_within_days)
        ).date().isoformat()
    pushed_before = str(getattr(args, "pushed_before", "") or "")
    if pushed_after and pushed_before:
        after = parse_github_datetime(pushed_after, upper_bound=False)
        before = parse_github_datetime(pushed_before, upper_bound=True)
        if after > before:
            raise SkillCliError("--pushed-after cannot be later than --pushed-before")

    return GitHubRepositoryFilters(
        legacy_owners=legacy_owners,
        organizations=organizations,
        users=users,
        repositories=repositories,
        all_github=all_github,
        min_stars=min_stars,
        max_stars=max_stars,
        pushed_after=pushed_after,
        pushed_before=pushed_before,
        created_after=created_after,
        created_before=created_before,
        language=str(getattr(args, "language", "") or "").strip(),
        topics=unique_casefolded(list(getattr(args, "topics", []) or [])),
        verified_orgs_only=bool(getattr(args, "verified_orgs_only", False)),
        max_repositories=getattr(args, "max_repositories", None),
    )


def validate_skill_slug(slug: str) -> str:
    normalized = slug.strip()
    if not normalized:
        raise SkillCliError("--slug is required or must be inferable from frontmatter name")
    if not SLUG_PATTERN.match(normalized):
        raise SkillCliError(
            "--slug must contain lowercase letters, numbers, hyphens, or underscores"
        )
    return normalized


def normalize_repo_subfolder(value: str) -> str:
    return value.strip().strip("/")


def validate_import_subfolder(value: str) -> str:
    subfolder = value.strip()
    if not subfolder:
        raise SkillCliError("--subfolder is required")
    try:
        validate_skill_file_path(f"{subfolder}/SKILL.md")
    except ValueError as exc:
        raise SkillCliError(f"invalid --subfolder: {exc}") from exc
    return subfolder


def read_skill_add_input(args: argparse.Namespace) -> SkillAddInput:
    skill_file = Path(args.skill_file).expanduser().resolve()
    if not skill_file.exists() or not skill_file.is_file():
        raise SkillCliError(f"skill file not found: {skill_file}")

    contents = skill_file.read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(contents)
    files = snapshot_files(contents)
    name = (args.name or frontmatter.get("name") or skill_file.parent.name).strip()
    description = (args.description or frontmatter.get("description") or "").strip()
    slug = validate_skill_slug(args.slug or slug_from_name(name))
    source = validate_skill_source(args.source, source_type=args.source_type)
    source_owner = (args.source_owner or source_owner_from_source(source)).strip()
    source_name = (args.source_name or source_name_from_source(source)).strip()
    inferred_source_url = github_source_url(source) if args.source_type == "github" else source
    inferred_source_owner_url = (
        github_owner_url(source_owner) if args.source_type == "github" and source_owner else ""
    )
    source_url = (args.source_url or args.repository_url or inferred_source_url).strip()
    source_owner_url = (args.source_owner_url or inferred_source_owner_url).strip()
    source_owner_icon_url = (args.source_owner_icon_url or "").strip()
    install_url = args.install_url or source_url
    website_url = args.website_url or install_url
    repository_url = args.repository_url or install_url
    return SkillAddInput(
        source=source,
        source_owner=source_owner,
        source_name=source_name,
        source_owner_url=source_owner_url,
        source_owner_icon_url=source_owner_icon_url,
        source_url=source_url,
        slug=slug,
        name=name,
        description=description,
        skill_md=contents,
        files=files,
        source_type=args.source_type,
        install_url=install_url,
        website_url=website_url,
        repository_url=repository_url,
    )


def snapshot_files(contents: str) -> list[SkillSnapshotFile]:
    return [{"path": "SKILL.md", "contents": contents}]


def content_hash(files: list[SkillSnapshotFile]) -> str:
    payload = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def repository_payload(payload: SkillAddInput) -> dict[str, str]:
    repository = {
        "type": "git",
        "source": payload.source_type,
        "url": payload.repository_url,
    }
    if payload.repository_subfolder:
        repository["subfolder"] = payload.repository_subfolder
    if payload.repository_ref:
        repository["branch"] = payload.repository_ref
    return repository


async def upsert_skill_snapshot(
    session: AsyncSession,
    skill: Skill,
    *,
    skill_md: str,
    files: list[SkillSnapshotFile],
) -> SkillSnapshot:
    hash_value = content_hash(files)
    frontmatter = parse_frontmatter(skill_md)
    previous_snapshot_id = skill.current_snapshot_id
    await session.execute(
        select(Skill.id).where(Skill.id == skill.id).with_for_update()
    )
    await session.execute(
        update(SkillSnapshot)
        .where(SkillSnapshot.skill_id == skill.id)
        .values(is_latest=False)
    )
    result = await session.execute(
        select(SkillSnapshot).where(
            SkillSnapshot.skill_id == skill.id,
            SkillSnapshot.content_hash == hash_value,
        )
    )
    snapshot = result.scalar_one_or_none()
    if snapshot is None:
        snapshot = SkillSnapshot(
            skill_id=skill.id,
            content_hash=hash_value,
            skill_md=skill_md,
            metadata_=frontmatter,
            files=files,
            status="active",
            is_latest=True,
        )
        session.add(snapshot)
        await session.flush()
    else:
        if snapshot.status == "quarantined":
            raise SkillCliError("refusing to reactivate quarantined skill content")
        snapshot.skill_md = skill_md
        snapshot.metadata_ = frontmatter
        snapshot.files = files
        snapshot.status = "active"
        snapshot.is_latest = True

    if previous_snapshot_id is not None and previous_snapshot_id != snapshot.id:
        await session.execute(delete(SkillAudit).where(SkillAudit.skill_id == skill.id))
    skill.current_snapshot_id = snapshot.id
    return snapshot


async def add_skill(
    session: AsyncSession,
    payload: SkillAddInput,
    *,
    preserve_catalog_state: bool = False,
) -> tuple[Skill, SkillSnapshot]:
    if payload.source_type == "github":
        owner_lock_key = f"wardn-hub:github-owner:{payload.source_owner.casefold()}"
        await session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(owner_lock_key, 0)
                )
            )
        )
    source_filter = Skill.source == payload.source
    if payload.source_type == "github":
        source_filter = func.lower(Skill.source) == payload.source.lower()
    skill: Skill | None = None
    if preserve_catalog_state and payload.repository_subfolder:
        result = await session.execute(
            select(Skill).where(
                Skill.source_type == payload.source_type,
                source_filter,
                Skill.repository["subfolder"].as_string()
                == payload.repository_subfolder,
            )
        )
        skill = result.scalar_one_or_none()

    if skill is None:
        result = await session.execute(
            select(Skill).where(
                Skill.source_type == payload.source_type,
                source_filter,
                Skill.slug == payload.slug,
            )
        )
        skill = result.scalar_one_or_none()
        if skill is not None and preserve_catalog_state and payload.repository_subfolder:
            existing_repository = skill.repository
            existing_subfolder = (
                existing_repository.get("subfolder")
                if isinstance(existing_repository, dict)
                else None
            )
            if existing_subfolder and existing_subfolder != payload.repository_subfolder:
                raise SkillCliError(
                    f"skill slug {payload.slug} already belongs to repository subfolder "
                    f"{existing_subfolder}"
                )
    if skill is None:
        skill = Skill(
            source_type=payload.source_type,
            source=payload.source,
            source_owner=payload.source_owner,
            source_name=payload.source_name,
            source_owner_url=payload.source_owner_url,
            source_owner_icon_url=payload.source_owner_icon_url,
            source_url=payload.source_url,
            slug=payload.slug,
            name=payload.name,
            description=payload.description,
            install_url=payload.install_url,
            website_url=payload.website_url,
            repository=repository_payload(payload),
            installs=0,
            status="active",
            visibility="public",
        )
        session.add(skill)
        await session.flush()
    else:
        skill.name = payload.name
        skill.source_owner = payload.source_owner
        skill.source_name = payload.source_name
        skill.source_owner_url = payload.source_owner_url
        skill.source_owner_icon_url = payload.source_owner_icon_url
        skill.source_url = payload.source_url
        skill.description = payload.description
        skill.install_url = payload.install_url
        skill.website_url = payload.website_url
        skill.repository = repository_payload(payload)
        if not preserve_catalog_state:
            skill.status = "active"
            skill.visibility = "public"

    snapshot = await upsert_skill_snapshot(
        session,
        skill,
        skill_md=payload.skill_md,
        files=payload.files,
    )
    await upsert_source_owner_metadata(session, payload)
    return skill, snapshot


async def upsert_source_owner_metadata(session: AsyncSession, payload: SkillAddInput) -> None:
    if not payload.source_owner:
        return

    result = await session.execute(
        select(SkillSourceOwner).where(
            SkillSourceOwner.source_type == payload.source_type,
            SkillSourceOwner.source_owner.ilike(payload.source_owner),
        )
    )
    source_owner = result.scalar_one_or_none()
    if source_owner is None:
        source_owner = SkillSourceOwner(
            source_type=payload.source_type,
            source_owner=payload.source_owner,
            source_owner_url=payload.source_owner_url,
            source_owner_icon_url=payload.source_owner_icon_url,
            is_official=False,
        )
        session.add(source_owner)
        return

    source_owner.source_owner = payload.source_owner
    if payload.source_owner_url:
        source_owner.source_owner_url = payload.source_owner_url
    if payload.source_owner_icon_url:
        source_owner.source_owner_icon_url = payload.source_owner_icon_url


async def add_skill_from_args(args: argparse.Namespace) -> int:
    payload = read_skill_add_input(args)
    async with AsyncSessionLocal() as session:
        skill, snapshot = await add_skill(session, payload)
        await session.commit()

    skill_id = f"{skill.source}/{skill.slug}"
    print(f"added skill {skill_id}")
    print(f"snapshot {snapshot.content_hash}")
    print(f"detail /api/v1/skills/{skill_id}")
    print(f"search /api/v1/skills/search?q={skill.slug}")
    return 0


def parse_github_repository_url(repository_url: str) -> GitHubRepository:
    parsed = urlparse(repository_url.strip())
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise SkillCliError("repository URL must be a github.com URL")

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise SkillCliError("repository URL must look like https://github.com/owner/repo")

    owner = parts[0]
    repo = parts[1].removesuffix(".git")
    ref = ""
    path = ""
    if len(parts) >= 4 and parts[2] in {"tree", "blob"}:
        ref = parts[3]
        path = "/".join(parts[4:])
    return GitHubRepository(
        owner=owner,
        repo=repo,
        url=f"https://github.com/{owner}/{repo}",
        path=path,
        ref=ref,
    )


def parse_github_datetime(value: str, *, upper_bound: bool) -> datetime:
    normalized = value.strip()
    is_date = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized))
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SkillCliError(f"invalid GitHub timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    else:
        parsed = parsed.astimezone(UTC)
    if upper_bound and is_date:
        parsed += timedelta(days=1, seconds=-1)
    return parsed.replace(microsecond=0)


def github_search_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def github_created_window(filters: GitHubRepositoryFilters) -> tuple[datetime, datetime]:
    start = (
        parse_github_datetime(filters.created_after, upper_bound=False)
        if filters.created_after
        else GITHUB_CREATED_AT_FLOOR
    )
    end = (
        parse_github_datetime(filters.created_before, upper_bound=True)
        if filters.created_before
        else datetime.now(tz=UTC) + timedelta(days=1)
    )
    return start, end


def github_repository_search_query(
    filters: GitHubRepositoryFilters,
    target: GitHubSearchTarget,
    *,
    created_start: datetime,
    created_end: datetime,
) -> str:
    qualifiers = ["is:public", "archived:false"]
    if target.qualifier:
        qualifiers.append(f"{target.qualifier}:{target.value}")
    if filters.min_stars is not None:
        qualifiers.append(f"stars:>={filters.min_stars}")
    if filters.max_stars is not None:
        qualifiers.append(f"stars:<={filters.max_stars}")
    if filters.pushed_after:
        qualifiers.append(f"pushed:>={filters.pushed_after}")
    if filters.pushed_before:
        qualifiers.append(f"pushed:<={filters.pushed_before}")
    if filters.language:
        qualifiers.append(f'language:"{filters.language}"')
    qualifiers.extend(f"topic:{topic}" for topic in filters.topics)
    qualifiers.append(
        "created:"
        f"{github_search_timestamp(created_start)}..{github_search_timestamp(created_end)}"
    )
    return " ".join(qualifiers)


def github_repository_from_search_item(
    item: dict[str, object],
) -> tuple[GitHubImportRepository | None, str]:
    if (
        item.get("private") is not False
        or item.get("fork") is not False
        or item.get("archived") is not False
        or item.get("disabled") is not False
    ):
        return None, "repository is private, forked, archived, or disabled"
    visibility = item.get("visibility")
    if visibility not in {None, "public"}:
        return None, "repository is not public"

    name_value = item.get("name")
    full_name_value = item.get("full_name")
    owner_value = item.get("owner")
    if not isinstance(name_value, str) or not name_value.strip():
        raise GitHubSystemicError("GitHub repository search result has no repository name")
    if not isinstance(full_name_value, str) or not isinstance(owner_value, dict):
        raise GitHubSystemicError("GitHub repository search result has invalid ownership")
    owner_login_value = owner_value.get("login")
    owner_type = owner_value.get("type")
    if not isinstance(owner_login_value, str) or owner_type not in {"User", "Organization"}:
        raise GitHubSystemicError("GitHub repository search result has invalid owner metadata")
    try:
        owner_login = validate_github_owner(owner_login_value)
    except SkillCliError as exc:
        raise GitHubSystemicError(
            "GitHub repository search result has an invalid owner login"
        ) from exc
    name = name_value.strip()
    expected_source = f"{owner_login}/{name}"
    if full_name_value.casefold() != expected_source.casefold():
        raise GitHubSystemicError("GitHub repository search result has inconsistent ownership")
    default_branch_value = item.get("default_branch")
    default_branch = (
        default_branch_value.strip() if isinstance(default_branch_value, str) else ""
    )
    avatar_value = owner_value.get("avatar_url")
    avatar_url = avatar_value.strip() if isinstance(avatar_value, str) else ""
    return (
        GitHubImportRepository(
            repo=GitHubRepository(
                owner=owner_login,
                repo=name,
                url=f"https://github.com/{owner_login}/{name}",
            ),
            default_branch=default_branch,
            owner_avatar_url=avatar_url,
        ),
        str(owner_type),
    )


class GitHubClient:
    def __init__(
        self,
        *,
        token: str = "",
        timeout_seconds: float = DEFAULT_IMPORT_TIMEOUT_SECONDS,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": user_agent,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token.strip():
            headers["Authorization"] = f"Bearer {token.strip()}"
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            headers=headers,
            follow_redirects=True,
            event_hooks={"request": [validate_github_request]},
        )
        self._verified_org_cache: OrderedDict[str, bool] = OrderedDict()

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._client.aclose()

    async def _get(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        follow_redirects: bool | None = None,
    ) -> httpx.Response:
        rate_limit_retry_attempt = 0
        transient_retry_attempt = 0
        while True:
            request_kwargs: dict[str, object] = {}
            if params is not None:
                request_kwargs["params"] = params
            if follow_redirects is not None:
                request_kwargs["follow_redirects"] = follow_redirects
            try:
                response = await self._client.get(  # type: ignore[arg-type]
                    url,
                    **request_kwargs,
                )
            except httpx.TransportError as exc:
                if transient_retry_attempt >= GITHUB_TRANSIENT_MAX_RETRIES:
                    detail = str(exc).strip() or "empty error message"
                    raise GitHubSystemicError(
                        "GitHub request failed after "
                        f"{transient_retry_attempt + 1} attempts: "
                        f"{type(exc).__name__}: {detail}"
                    ) from exc
                retry_wait = github_transient_retry_wait(transient_retry_attempt)
                transient_retry_attempt += 1
                logger.warning(
                    "github request transient failure; waiting before retry",
                    extra={
                        "request_host": urlparse(url).hostname,
                        "request_path": urlparse(url).path,
                        "failure_type": type(exc).__name__,
                        "retry_attempt": transient_retry_attempt,
                        "retry_wait_seconds": retry_wait,
                    },
                )
                await asyncio.sleep(retry_wait)
                continue
            wait = github_rate_limit_wait(
                response,
                retry_attempt=rate_limit_retry_attempt,
                now_epoch_seconds=time.time(),
            )
            if wait is not None:
                rate_limit_retry_attempt += 1
                logger.warning(
                    "github request rate limited; waiting before retry",
                    extra={
                        "request_host": urlparse(url).hostname,
                        "request_path": urlparse(url).path,
                        "rate_limit_reason": wait.reason,
                        "rate_limit_resource": github_response_header(
                            response, "x-ratelimit-resource"
                        ),
                        "rate_limit_remaining": github_response_header(
                            response, "x-ratelimit-remaining"
                        ),
                        "rate_limit_reset": github_response_header(
                            response, "x-ratelimit-reset"
                        ),
                        "retry_attempt": rate_limit_retry_attempt,
                        "retry_wait_seconds": wait.seconds,
                    },
                )
                await asyncio.sleep(wait.seconds)
                continue
            if response.status_code < 500:
                return response
            if transient_retry_attempt >= GITHUB_TRANSIENT_MAX_RETRIES:
                return response
            retry_wait = github_transient_retry_wait(transient_retry_attempt)
            transient_retry_attempt += 1
            logger.warning(
                "github request transient failure; waiting before retry",
                extra={
                    "request_host": urlparse(url).hostname,
                    "request_path": urlparse(url).path,
                    "failure_type": "http_status",
                    "http_status_code": response.status_code,
                    "github_request_id": github_response_header(
                        response, "x-github-request-id"
                    ),
                    "retry_attempt": transient_retry_attempt,
                    "retry_wait_seconds": retry_wait,
                },
            )
            await asyncio.sleep(retry_wait)

    async def owner(self, owner: str) -> GitHubOwner:
        response = await self._get(
            f"{GITHUB_API_ROOT}/users/{quote(owner, safe='')}"
        )
        if response.status_code == 404:
            raise SkillCliError(f"GitHub user or organization not found: {owner}")
        if response.status_code >= 400:
            raise github_http_error(
                response.status_code,
                github_response_error_message(response, "GitHub owner lookup failed"),
            )
        payload = github_json(response, "owner metadata")
        if not isinstance(payload, dict):
            raise GitHubSystemicError("GitHub returned invalid owner metadata")

        login_value = payload.get("login")
        account_type = payload.get("type")
        if not isinstance(login_value, str):
            raise GitHubSystemicError("GitHub owner metadata has no login")
        try:
            login = validate_github_owner(login_value)
        except SkillCliError as exc:
            raise GitHubSystemicError("GitHub owner metadata has an invalid login") from exc
        if account_type not in {"User", "Organization"}:
            raise SkillCliError(
                f"GitHub owner must be a user or organization, not {account_type or 'unknown'}"
            )
        avatar_value = payload.get("avatar_url")
        avatar_url = avatar_value.strip() if isinstance(avatar_value, str) else ""
        return GitHubOwner(
            login=login,
            account_type=account_type,
            avatar_url=avatar_url,
        )

    async def organization_is_verified(self, owner: str) -> bool:
        cache_key = owner.casefold()
        cached = self._verified_org_cache.get(cache_key)
        if cached is not None:
            self._verified_org_cache.move_to_end(cache_key)
            return cached
        response = await self._get(
            f"{GITHUB_API_ROOT}/orgs/{quote(owner, safe='')}"
        )
        if response.status_code == 404:
            return False
        if response.status_code >= 400:
            raise github_http_error(
                response.status_code,
                github_response_error_message(
                    response,
                    "GitHub organization lookup failed",
                ),
            )
        payload = github_json(response, "organization metadata")
        if not isinstance(payload, dict) or not isinstance(payload.get("is_verified"), bool):
            raise GitHubSystemicError("GitHub organization metadata has no verified status")
        verified = payload["is_verified"]
        self._verified_org_cache[cache_key] = verified
        self._verified_org_cache.move_to_end(cache_key)
        if len(self._verified_org_cache) > GITHUB_VERIFIED_ORG_CACHE_SIZE:
            self._verified_org_cache.popitem(last=False)
        return verified

    async def search_repository_page(
        self,
        query: str,
        *,
        page: int,
    ) -> GitHubRepositorySearchPage:
        response = await self._get(
            f"{GITHUB_API_ROOT}/search/repositories",
            params={
                "q": query,
                "sort": "updated",
                "order": "desc",
                "page": str(page),
                "per_page": str(GITHUB_REPOSITORIES_PER_PAGE),
            },
        )
        if response.status_code >= 400:
            raise github_http_error(
                response.status_code,
                github_response_error_message(
                    response,
                    "GitHub repository search failed",
                ),
            )
        payload = github_json(response, "repository search")
        if not isinstance(payload, dict):
            raise GitHubSystemicError("GitHub returned an invalid repository search response")
        total_count = payload.get("total_count")
        incomplete_results = payload.get("incomplete_results")
        items = payload.get("items")
        if (
            not isinstance(total_count, int)
            or total_count < 0
            or not isinstance(incomplete_results, bool)
            or not isinstance(items, list)
            or any(not isinstance(item, dict) for item in items)
        ):
            raise GitHubSystemicError("GitHub returned an invalid repository search response")
        if incomplete_results:
            raise GitHubSystemicError("GitHub repository search returned incomplete results")
        return GitHubRepositorySearchPage(
            total_count=total_count,
            incomplete_results=incomplete_results,
            items=items,
        )

    async def _search_repository_window(
        self,
        filters: GitHubRepositoryFilters,
        target: GitHubSearchTarget,
        *,
        created_start: datetime,
        created_end: datetime,
        stats: GitHubDiscoveryStats,
        budget: GitHubSearchBudget,
    ) -> AsyncIterator[GitHubImportRepository]:
        if budget.exhausted:
            return
        query = github_repository_search_query(
            filters,
            target,
            created_start=created_start,
            created_end=created_end,
        )
        first_page = await self.search_repository_page(query, page=1)
        stats.search_query_count += 1
        remaining_budget = budget.remaining
        must_split = (
            first_page.total_count > GITHUB_SEARCH_RESULT_LIMIT
            and (remaining_budget is None or remaining_budget > GITHUB_SEARCH_RESULT_LIMIT)
        )
        if must_split:
            if created_start >= created_end:
                raise SkillCliError(
                    "GitHub search has more than 1,000 repositories with the same creation "
                    "timestamp; add a narrower target or repository filter"
                )
            midpoint = created_start + (created_end - created_start) / 2
            midpoint = midpoint.replace(microsecond=0)
            if midpoint < created_start:
                midpoint = created_start
            right_start = midpoint + timedelta(seconds=1)
            if right_start > created_end:
                raise SkillCliError(
                    "GitHub search cannot split a result window below one second; "
                    "add a narrower target or repository filter"
                )
            async for repository in self._search_repository_window(
                filters,
                target,
                created_start=created_start,
                created_end=midpoint,
                stats=stats,
                budget=budget,
            ):
                yield repository
            async for repository in self._search_repository_window(
                filters,
                target,
                created_start=right_start,
                created_end=created_end,
                stats=stats,
                budget=budget,
            ):
                yield repository
            return

        maximum_results = min(first_page.total_count, GITHUB_SEARCH_RESULT_LIMIT)
        page_count = (maximum_results + GITHUB_REPOSITORIES_PER_PAGE - 1) // (
            GITHUB_REPOSITORIES_PER_PAGE
        )
        for page_number in range(1, page_count + 1):
            if budget.exhausted:
                return
            page = (
                first_page
                if page_number == 1
                else await self.search_repository_page(query, page=page_number)
            )
            if page_number > 1:
                stats.search_query_count += 1
            stats.listed_repository_count += len(page.items)
            for raw_item in page.items:
                candidate, owner_type = github_repository_from_search_item(raw_item)
                if candidate is None:
                    stats.filtered_repository_count += 1
                    continue
                if filters.verified_orgs_only:
                    if owner_type != "Organization" or not await self.organization_is_verified(
                        candidate.repo.owner
                    ):
                        stats.filtered_repository_count += 1
                        continue
                if not budget.consume():
                    return
                stats.active_repository_count += 1
                yield candidate

    async def iter_repositories(
        self,
        filters: GitHubRepositoryFilters,
        stats: GitHubDiscoveryStats,
    ) -> AsyncIterator[GitHubImportRepository]:
        targets: list[GitHubSearchTarget] = []
        for requested_owner in filters.legacy_owners:
            owner = await self.owner(requested_owner)
            qualifier = "org" if owner.account_type == "Organization" else "user"
            targets.append(
                GitHubSearchTarget(
                    qualifier=qualifier,
                    value=owner.login,
                    avatar_url=owner.avatar_url,
                )
            )
        targets.extend(
            GitHubSearchTarget(qualifier="org", value=owner)
            for owner in filters.organizations
        )
        targets.extend(
            GitHubSearchTarget(qualifier="user", value=owner) for owner in filters.users
        )
        targets.extend(
            GitHubSearchTarget(qualifier="repo", value=repository)
            for repository in filters.repositories
            if repository.split("/", 1)[0].casefold()
            not in {
                *(owner.casefold() for owner in filters.legacy_owners),
                *(owner.casefold() for owner in filters.organizations),
                *(owner.casefold() for owner in filters.users),
            }
        )
        if filters.all_github:
            targets.append(GitHubSearchTarget(qualifier="", value=""))

        unique_targets: dict[tuple[str, str], GitHubSearchTarget] = {}
        for target in targets:
            unique_targets.setdefault(
                (target.qualifier, target.value.casefold()),
                target,
            )
        start, end = github_created_window(filters)
        budget = GitHubSearchBudget(remaining=filters.max_repositories)
        for target in unique_targets.values():
            if budget.exhausted:
                break
            if filters.verified_orgs_only and target.qualifier == "user":
                continue
            if (
                filters.verified_orgs_only
                and target.qualifier == "org"
                and not await self.organization_is_verified(target.value)
            ):
                continue
            async for repository in self._search_repository_window(
                filters,
                target,
                created_start=start,
                created_end=end,
                stats=stats,
                budget=budget,
            ):
                yield repository

    async def list_active_repositories(self, owner: str) -> GitHubRepositoryListing:
        owner_metadata = await self.owner(owner)
        encoded_owner = quote(owner_metadata.login, safe="")
        if owner_metadata.account_type == "Organization":
            page_url = f"{GITHUB_API_ROOT}/orgs/{encoded_owner}/repos"
            repository_type = "public"
        else:
            page_url = f"{GITHUB_API_ROOT}/users/{encoded_owner}/repos"
            repository_type = "owner"
        params: dict[str, str] | None = {
            "type": repository_type,
            "sort": "full_name",
            "direction": "asc",
            "per_page": str(GITHUB_REPOSITORIES_PER_PAGE),
        }
        seen_pages: set[str] = set()
        repositories: dict[str, GitHubImportRepository] = {}
        listed_count = 0

        while page_url:
            if page_url in seen_pages:
                raise GitHubSystemicError("GitHub repository pagination repeated a page")
            seen_pages.add(page_url)
            if params is None:
                response = await self._get(page_url)
            else:
                response = await self._get(page_url, params=params)
            if response.status_code == 404:
                raise SkillCliError(
                    f"GitHub repositories not found for owner: {owner_metadata.login}"
                )
            if response.status_code >= 400:
                raise github_http_error(
                    response.status_code,
                    github_response_error_message(
                        response,
                        "GitHub repository listing failed",
                    ),
                )
            payload = github_json(response, "repository listing")
            if not isinstance(payload, list):
                raise GitHubSystemicError("GitHub returned an invalid repository listing")
            listed_count += len(payload)

            for item in payload:
                if not isinstance(item, dict):
                    raise GitHubSystemicError("GitHub repository listing contains an invalid item")
                if (
                    item.get("private") is not False
                    or item.get("fork") is not False
                    or item.get("archived") is not False
                    or item.get("disabled") is not False
                ):
                    continue
                visibility = item.get("visibility")
                if visibility not in {None, "public"}:
                    continue
                name_value = item.get("name")
                full_name_value = item.get("full_name")
                if not isinstance(name_value, str) or not name_value.strip():
                    raise GitHubSystemicError("GitHub repository listing has no repository name")
                name = name_value.strip()
                expected_source = f"{owner_metadata.login}/{name}"
                if (
                    not isinstance(full_name_value, str)
                    or full_name_value.casefold() != expected_source.casefold()
                ):
                    raise GitHubSystemicError(
                        "GitHub repository listing returned a repository for another owner"
                    )
                default_branch_value = item.get("default_branch")
                default_branch = (
                    default_branch_value.strip()
                    if isinstance(default_branch_value, str)
                    else ""
                )
                repository = GitHubImportRepository(
                    repo=GitHubRepository(
                        owner=owner_metadata.login,
                        repo=name,
                        url=f"https://github.com/{owner_metadata.login}/{name}",
                    ),
                    default_branch=default_branch,
                )
                repositories.setdefault(expected_source.casefold(), repository)

            links = getattr(response, "links", {})
            next_link = links.get("next") if isinstance(links, dict) else None
            next_url = next_link.get("url") if isinstance(next_link, dict) else None
            if next_url is None:
                page_url = ""
                continue
            if not isinstance(next_url, str):
                raise GitHubSystemicError("GitHub returned an invalid repository next-page link")
            parsed_next = urlparse(next_url)
            if (
                parsed_next.scheme != "https"
                or parsed_next.netloc.lower() != "api.github.com"
                or parsed_next.fragment
            ):
                raise GitHubSystemicError("GitHub returned an unsafe repository next-page link")
            page_url = next_url
            params = None

        return GitHubRepositoryListing(
            owner=owner_metadata,
            repositories=sorted(
                repositories.values(),
                key=lambda item: item.repo.source.casefold(),
            ),
            listed_count=listed_count,
        )

    async def repository_metadata(self, repo: GitHubRepository) -> GitHubRepositoryMetadata:
        response = await self._get(
            f"https://api.github.com/repos/{repo.owner}/{repo.repo}"
        )
        if response.status_code == 404:
            raise SkillCliError(f"GitHub repository not found: {repo.source}")
        if response.status_code >= 400:
            raise github_http_error(
                response.status_code,
                github_response_error_message(
                    response,
                    "GitHub repository lookup failed",
                ),
            )
        payload = github_json(response, "repository metadata")
        if not isinstance(payload, dict):
            raise SkillCliError(f"GitHub returned invalid repository metadata: {repo.source}")
        is_private = payload.get("private")
        visibility = payload.get("visibility")
        if not isinstance(is_private, bool):
            raise SkillCliError(
                f"GitHub repository visibility is unavailable: {repo.source}"
            )
        if is_private or (isinstance(visibility, str) and visibility != "public"):
            raise SkillCliError(
                f"GitHub skills import only supports public repositories: {repo.source}"
            )
        fork = payload.get("fork")
        archived = payload.get("archived")
        disabled = payload.get("disabled")
        if not all(isinstance(value, bool) for value in (fork, archived, disabled)):
            raise SkillCliError(f"GitHub repository state is unavailable: {repo.source}")
        if fork or archived or disabled:
            raise SkillCliError(f"GitHub repository is not active: {repo.source}")
        full_name = payload.get("full_name")
        if (
            not isinstance(full_name, str)
            or full_name.casefold() != repo.source.casefold()
        ):
            raise SkillCliError(f"GitHub repository moved to another owner: {repo.source}")
        default_branch = payload.get("default_branch")
        if not isinstance(default_branch, str) or not default_branch.strip():
            raise SkillCliError(f"GitHub repository has no default branch: {repo.source}")
        owner = payload.get("owner")
        owner_avatar_url = ""
        if isinstance(owner, dict) and isinstance(owner.get("avatar_url"), str):
            owner_avatar_url = owner["avatar_url"].strip()
        return GitHubRepositoryMetadata(
            default_branch=default_branch.strip(),
            owner_avatar_url=owner_avatar_url,
            fork=fork,
            archived=archived,
            disabled=disabled,
        )

    async def resolve_commit_sha(self, repo: GitHubRepository, ref: str) -> str:
        response = await self._get(
            f"https://api.github.com/repos/{repo.owner}/{repo.repo}/commits",
            params={"sha": ref, "per_page": "1"},
        )
        if response.status_code == 409:
            raise SkillNotFoundError(f"GitHub repository has no commits: {repo.source}")
        if response.status_code == 404:
            raise SkillCliError(f"GitHub ref not found for {repo.source}: {ref}")
        if response.status_code >= 400:
            raise github_http_error(
                response.status_code,
                github_response_error_message(response, "GitHub ref lookup failed"),
            )
        payload = github_json(response, "commit listing")
        if not isinstance(payload, list) or not payload:
            raise SkillCliError(f"GitHub ref has no commits for {repo.source}: {ref}")
        commit_sha = payload[0].get("sha") if isinstance(payload[0], dict) else None
        if not isinstance(commit_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha):
            raise SkillCliError(f"GitHub returned an invalid commit SHA for {repo.source}: {ref}")
        return commit_sha.lower()

    async def recursive_tree(self, repo: GitHubRepository, ref: str) -> list[GitHubTreeItem]:
        response = await self._get(
            f"https://api.github.com/repos/{repo.owner}/{repo.repo}/git/trees/{ref}",
            params={"recursive": "1"},
        )
        if response.status_code == 404:
            raise SkillCliError(f"GitHub ref not found for {repo.source}: {ref}")
        if response.status_code >= 400:
            raise github_http_error(
                response.status_code,
                github_response_error_message(response, "GitHub tree lookup failed"),
            )
        payload = github_json(response, "repository tree")
        if not isinstance(payload, dict):
            raise GitHubSystemicError("GitHub returned an invalid repository tree")
        truncated = payload.get("truncated")
        tree_payload = payload.get("tree")
        if not isinstance(truncated, bool) or not isinstance(tree_payload, list):
            raise GitHubSystemicError("GitHub returned an invalid repository tree")
        if truncated:
            raise GitHubTreeTruncatedError(
                "GitHub tree is truncated; repository scan skipped"
            )
        tree: list[GitHubTreeItem] = []
        for item in tree_payload:
            if not isinstance(item, dict):
                raise GitHubSystemicError("GitHub repository tree contains an invalid item")
            path = item.get("path")
            item_type = item.get("type")
            size = item.get("size", 0)
            mode = item.get("mode")
            if (
                not isinstance(path, str)
                or not path
                or not isinstance(item_type, str)
                or not item_type
                or not isinstance(size, int)
                or isinstance(size, bool)
                or not isinstance(mode, str)
                or not mode
            ):
                raise GitHubSystemicError("GitHub repository tree contains an invalid item")
            tree.append(
                GitHubTreeItem(
                    path=path,
                    type=item_type,
                    size=size,
                    mode=mode,
                )
            )
        return tree

    async def raw_file_bytes(
        self,
        repo: GitHubRepository,
        ref: str,
        path: str,
    ) -> bytes:
        encoded_ref = "/".join(quote(part, safe="") for part in ref.split("/"))
        encoded_path = "/".join(quote(part, safe="") for part in path.split("/"))
        response = await self._get(
            f"https://raw.githubusercontent.com/{repo.owner}/{repo.repo}/"
            f"{encoded_ref}/{encoded_path}",
            follow_redirects=False,
        )
        if 300 <= response.status_code < 400:
            raise SkillCliError(f"GitHub raw file redirected unexpectedly: {path}")
        if response.status_code == 404:
            raise SkillCliError(f"GitHub file not found: {path}")
        if response.status_code >= 400:
            raise github_http_error(
                response.status_code,
                github_response_error_message(
                    response,
                    f"GitHub raw file fetch failed for {path}",
                ),
            )
        return response.content

    async def raw_file(self, repo: GitHubRepository, ref: str, path: str) -> str:
        content = await self.raw_file_bytes(repo, ref, path)
        nul_offset = content.find(b"\x00")
        if nul_offset >= 0:
            line_number = content.count(b"\n", 0, nul_offset) + 1
            raise InvalidSkillTextError(
                path,
                f"GitHub file contains a NUL byte at offset {nul_offset} "
                f"(line {line_number})",
            )
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidSkillTextError(path, "GitHub file is not UTF-8 text") from exc
        control = unsupported_text_control(decoded)
        if control is not None:
            offset, character = control
            raise InvalidSkillTextError(
                path,
                "GitHub file contains unsupported control character "
                f"U+{ord(character):04X} at character offset {offset}",
            )
        return decoded


def tree_blob_paths(tree: list[GitHubTreeItem]) -> set[str]:
    return {item.path for item in tree if item.type == "blob"}


def should_skip_tree_path(path: str) -> bool:
    return any(part in SKIPPED_PATH_PARTS for part in PurePosixPath(path).parts)


def skill_root_from_skill_path(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return "" if parent == "." else parent


def relative_skill_file_path(root: str, path: str) -> str:
    if not root:
        return path
    return str(PurePosixPath(path).relative_to(root))


def validate_skill_file_path(path: str) -> str:
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or any(ord(character) < 32 or ord(character) == 127 for character in path)
    ):
        raise ValueError("skill file path must be a safe relative POSIX path")

    normalized = PurePosixPath(path).as_posix()
    if normalized != path or any(part in {"", ".", ".."} for part in path.split("/")):
        raise ValueError("skill file path must be a normalized relative POSIX path")
    return normalized


def path_is_within_skill_root(path: str, root: str) -> bool:
    return not root or path.startswith(f"{root}/")


def skill_bundle_tree_items(
    tree: list[GitHubTreeItem],
    *,
    skill_path: str,
) -> list[GitHubTreeItem]:
    root = skill_root_from_skill_path(skill_path)
    skill_roots = {
        skill_root_from_skill_path(item.path)
        for item in tree
        if item.type == "blob"
        and item.mode != "120000"
        and PurePosixPath(item.path).name == "SKILL.md"
        and not should_skip_tree_path(item.path)
    }

    owned_items: list[GitHubTreeItem] = []
    relative_paths: set[str] = set()
    for item in tree:
        if (
            item.type != "blob"
            or item.mode == "120000"
            or should_skip_tree_path(item.path)
            or not path_is_within_skill_root(item.path, root)
        ):
            continue

        owning_roots = [
            candidate
            for candidate in skill_roots
            if path_is_within_skill_root(item.path, candidate)
        ]
        if not owning_roots:
            continue
        owner = max(owning_roots, key=lambda value: len(PurePosixPath(value).parts))
        if owner != root:
            continue

        relative_path = relative_skill_file_path(root, item.path)
        try:
            relative_path = validate_skill_file_path(relative_path)
        except ValueError as exc:
            raise InvalidSkillBundleError(item.path, str(exc)) from exc
        if relative_path in relative_paths:
            raise InvalidSkillBundleError(item.path, "duplicate skill file path")
        relative_paths.add(relative_path)
        owned_items.append(item)

    if "SKILL.md" not in relative_paths:
        raise InvalidSkillBundleError(skill_path, "skill root is not a regular file")
    if len(owned_items) > MAX_SKILL_BUNDLE_FILES:
        raise InvalidSkillBundleError(
            skill_path,
            f"skill bundle exceeds {MAX_SKILL_BUNDLE_FILES} files",
        )

    advertised_size = 0
    for item in owned_items:
        if item.size < 0:
            raise InvalidSkillBundleError(item.path, "GitHub tree reported a negative file size")
        if item.size > MAX_SKILL_FILE_BYTES:
            raise InvalidSkillBundleError(
                item.path,
                f"skill file exceeds {MAX_SKILL_FILE_BYTES} bytes",
            )
        advertised_size += item.size
    if advertised_size > MAX_SKILL_BUNDLE_BYTES:
        raise InvalidSkillBundleError(
            skill_path,
            f"skill bundle exceeds {MAX_SKILL_BUNDLE_BYTES} bytes",
        )

    return sorted(
        owned_items,
        key=lambda item: (
            relative_skill_file_path(root, item.path) != "SKILL.md",
            relative_skill_file_path(root, item.path),
        ),
    )


def snapshot_file_from_bytes(
    *,
    path: str,
    contents: bytes,
    executable: bool,
) -> SkillSnapshotFile:
    encoding: SkillFileEncoding = "utf-8"
    try:
        rendered_contents = contents.decode("utf-8")
    except UnicodeDecodeError:
        encoding = "base64"
        rendered_contents = base64.b64encode(contents).decode("ascii")
    else:
        if unsupported_text_control(rendered_contents) is not None:
            encoding = "base64"
            rendered_contents = base64.b64encode(contents).decode("ascii")

    file: SkillSnapshotFile = {"path": path, "contents": rendered_contents}
    if encoding == "base64":
        file["encoding"] = encoding
    if executable:
        file["executable"] = True
    return file


async def fetch_skill_bundle(
    *,
    client: GitHubClient,
    repo: GitHubRepository,
    ref: str,
    tree: list[GitHubTreeItem],
    skill_path: str,
    items: list[GitHubTreeItem] | None = None,
) -> tuple[str, list[SkillSnapshotFile], int]:
    root = skill_root_from_skill_path(skill_path)
    if items is None:
        items = skill_bundle_tree_items(tree, skill_path=skill_path)
    skill_item = next(item for item in items if item.path == skill_path)
    skill_md = await client.raw_file(repo, ref, skill_path)
    if not skill_md.strip():
        raise InvalidSkillTextError(skill_path, "GitHub SKILL.md is empty")

    skill_contents = skill_md.encode("utf-8")
    if len(skill_contents) > MAX_SKILL_FILE_BYTES:
        raise InvalidSkillBundleError(
            skill_path,
            f"skill file exceeds {MAX_SKILL_FILE_BYTES} bytes",
        )
    skill_file: SkillSnapshotFile = {"path": "SKILL.md", "contents": skill_md}
    if skill_item.mode == "100755":
        skill_file["executable"] = True
    files = [skill_file]

    semaphore = asyncio.Semaphore(MAX_BUNDLE_FETCH_CONCURRENCY)

    async def fetch_supporting_file(
        item: GitHubTreeItem,
    ) -> tuple[SkillSnapshotFile, int]:
        async with semaphore:
            contents = await client.raw_file_bytes(repo, ref, item.path)
        if len(contents) > MAX_SKILL_FILE_BYTES:
            raise InvalidSkillBundleError(
                item.path,
                f"skill file exceeds {MAX_SKILL_FILE_BYTES} bytes",
            )
        relative_path = validate_skill_file_path(relative_skill_file_path(root, item.path))
        return (
            snapshot_file_from_bytes(
                path=relative_path,
                contents=contents,
                executable=item.mode == "100755",
            ),
            len(contents),
        )

    fetched = await asyncio.gather(
        *(fetch_supporting_file(item) for item in items if item.path != skill_path)
    )
    files.extend(file for file, _size in fetched)
    bundle_size = len(skill_contents) + sum(size for _file, size in fetched)
    if bundle_size > MAX_SKILL_BUNDLE_BYTES:
        raise InvalidSkillBundleError(
            skill_path,
            f"skill bundle exceeds {MAX_SKILL_BUNDLE_BYTES} bytes",
        )
    return skill_md, files, bundle_size


def skill_refresh_target(skill: Skill, current_hash: str | None) -> SkillRefreshTarget:
    skill_id = f"{skill.source}/{skill.slug}"
    repository_value = skill.repository
    if not isinstance(repository_value, dict):
        raise SkillCliError(f"skill has no recorded repository metadata: {skill_id}")
    repository: dict[str, object] = dict(repository_value)
    if repository.get("type") != "git" or repository.get("source") != "github":
        raise SkillCliError(f"skill repository is not a recorded GitHub source: {skill_id}")

    repository_url = repository.get("url")
    if not isinstance(repository_url, str) or not repository_url.strip():
        raise SkillCliError(f"skill repository URL is missing: {skill_id}")
    repo = parse_github_repository_url(repository_url)
    if repo.path or repo.ref:
        raise SkillCliError(f"skill repository URL must point at the repository root: {skill_id}")
    if repo.source.lower() != skill.source.lower():
        raise SkillCliError(
            f"skill repository does not match its source {skill.source}: {skill_id}"
        )

    subfolder_value = repository.get("subfolder", "")
    if not isinstance(subfolder_value, str):
        raise SkillCliError(f"skill repository subfolder is invalid: {skill_id}")
    subfolder = normalize_repo_subfolder(subfolder_value)
    skill_path = f"{subfolder}/SKILL.md" if subfolder else "SKILL.md"
    try:
        validate_skill_file_path(skill_path)
    except ValueError as exc:
        raise SkillCliError(f"invalid recorded skill path for {skill_id}: {exc}") from exc

    ref_value = repository.get("branch", "")
    if not isinstance(ref_value, str):
        raise SkillCliError(f"skill repository branch is invalid: {skill_id}")
    ref = ref_value.strip()
    if not ref:
        raise SkillCliError(f"skill has no recorded GitHub branch: {skill_id}")
    return SkillRefreshTarget(
        skill_id=skill.id,
        current_snapshot_id=skill.current_snapshot_id,
        current_hash=current_hash,
        source=skill.source,
        slug=skill.slug,
        repository=repository,
        repo=repo,
        subfolder=subfolder,
        ref=ref,
    )


async def load_skill_refresh_targets() -> tuple[list[SkillRefreshTarget], list[SkillRefreshIssue]]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                Skill,
                SkillSnapshot.content_hash,
                SkillSnapshot.status,
                SkillSnapshot.is_latest,
                SkillSnapshot.skill_id,
            )
            .outerjoin(
                SkillSnapshot,
                Skill.current_snapshot_id == SkillSnapshot.id,
            )
            .where(
                Skill.source_type == "github",
                Skill.status == "active",
            )
            .order_by(Skill.source.asc(), Skill.slug.asc())
        )
        rows = result.all()

    targets: list[SkillRefreshTarget] = []
    issues: list[SkillRefreshIssue] = []
    for skill, current_hash, snapshot_status, snapshot_is_latest, snapshot_skill_id in rows:
        skill_id = f"{skill.source}/{skill.slug}"
        if (
            skill.current_snapshot_id is None
            or snapshot_skill_id != skill.id
            or snapshot_status != "active"
            or snapshot_is_latest is not True
        ):
            issues.append(
                SkillRefreshIssue(
                    skill_id=skill_id,
                    reason="skill has no active latest current snapshot",
                )
            )
            continue
        try:
            targets.append(skill_refresh_target(skill, current_hash))
        except SkillCliError as exc:
            issues.append(
                SkillRefreshIssue(
                    skill_id=skill_id,
                    reason=str(exc),
                )
            )
    return targets, issues


async def refresh_existing_skill_snapshot(
    session: AsyncSession,
    target: SkillRefreshTarget,
    *,
    skill_md: str,
    files: list[SkillSnapshotFile],
) -> tuple[str, bool]:
    result = await session.execute(
        select(Skill).where(Skill.id == target.skill_id).with_for_update()
    )
    skill = result.scalar_one_or_none()
    if skill is None:
        raise SkillCliError(f"skill no longer exists: {target.id}")
    if (
        skill.source_type != "github"
        or skill.status != "active"
        or skill.source != target.source
        or skill.slug != target.slug
        or skill.repository != target.repository
        or skill.current_snapshot_id != target.current_snapshot_id
    ):
        raise SkillCliError(f"skill changed while refresh was running: {target.id}")

    snapshot_result = await session.execute(
        select(SkillSnapshot)
        .where(
            SkillSnapshot.id == target.current_snapshot_id,
            SkillSnapshot.skill_id == skill.id,
        )
        .with_for_update()
    )
    current_snapshot = snapshot_result.scalar_one_or_none()
    if (
        current_snapshot is None
        or current_snapshot.status != "active"
        or current_snapshot.is_latest is not True
        or current_snapshot.content_hash != target.current_hash
    ):
        raise SkillCliError(f"skill snapshot changed while refresh was running: {target.id}")

    hash_value = content_hash(files)
    if current_snapshot.content_hash == hash_value:
        return hash_value, False
    snapshot = await upsert_skill_snapshot(
        session,
        skill,
        skill_md=skill_md,
        files=files,
    )
    return snapshot.content_hash or hash_value, True


async def save_refreshed_skill(
    target: SkillRefreshTarget,
    *,
    skill_md: str,
    files: list[SkillSnapshotFile],
) -> tuple[str, bool]:
    async with AsyncSessionLocal() as session:
        try:
            result = await refresh_existing_skill_snapshot(
                session,
                target,
                skill_md=skill_md,
                files=files,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return result


def discover_skill_paths(
    tree: list[GitHubTreeItem],
    *,
    subfolder: str,
) -> list[str]:
    blobs = tree_blob_paths(tree)
    skill_path = f"{subfolder}/SKILL.md" if subfolder else "SKILL.md"
    if skill_path in blobs:
        return [skill_path]
    if subfolder:
        raise SkillNotFoundError(f"No SKILL.md found in GitHub subfolder: {subfolder}")
    raise SkillNotFoundError("No SKILL.md found in GitHub repository root")


async def import_skill_from_github_path(
    *,
    client: GitHubClient,
    repo: GitHubRepository,
    ref: str,
    tree: list[GitHubTreeItem],
    skill_path: str,
    fetch_ref: str,
    owner_avatar_url: str,
    import_subfolder: str,
    bundle_items: list[GitHubTreeItem] | None = None,
) -> ImportedSkill:
    root = skill_root_from_skill_path(skill_path)
    skill_md, files, bundle_size = await fetch_skill_bundle(
        client=client,
        repo=repo,
        ref=fetch_ref,
        tree=tree,
        skill_path=skill_path,
        items=bundle_items,
    )
    frontmatter = parse_frontmatter(skill_md)
    name = (frontmatter.get("name") or Path(root).name or repo.repo).strip()
    slug = validate_skill_slug(
        slug_from_skill_root(skill_slug_root(root, import_subfolder), name)
    )
    description = (frontmatter.get("description") or "").strip()
    repository_url = f"{repo.url}/tree/{fetch_ref}"
    if root:
        encoded_root = "/".join(quote(part, safe="") for part in root.split("/"))
        repository_url = f"{repository_url}/{encoded_root}"
    logger.info(
        "github skill import fetched skill file",
        extra={
            "source": repo.source,
            "ref": ref,
            "resolved_ref": fetch_ref,
            "source_path": skill_path,
            "skill_slug": slug,
            "skill_name": name,
            "skill_root": root,
            "skill_md_bytes": len(skill_md.encode("utf-8")),
            "skill_file_count": len(files),
            "skill_bundle_bytes": bundle_size,
        },
    )
    payload = SkillAddInput(
        source=repo.source,
        source_owner=repo.owner,
        source_name=repo.repo,
        source_owner_url=github_owner_url(repo.owner),
        source_owner_icon_url=owner_avatar_url,
        source_url=repo.url,
        slug=slug,
        name=name,
        description=description,
        skill_md=skill_md,
        files=files,
        source_type="github",
        install_url=repository_url,
        website_url=repository_url,
        repository_url=repo.url,
        repository_subfolder=root,
        repository_ref=ref,
    )
    return ImportedSkill(
        payload=payload,
        source_path=skill_path,
        bundle_size=bundle_size,
    )


def validate_unique_imported_skill_slugs(imported: list[ImportedSkill]) -> None:
    paths_by_slug: dict[str, str] = {}
    for item in imported:
        slug = item.payload.slug
        previous_path = paths_by_slug.get(slug)
        if previous_path is not None:
            raise SkillCliError(
                f"multiple skill paths resolve to slug {slug}: "
                f"{previous_path}, {item.source_path}"
            )
        paths_by_slug[slug] = item.source_path


async def save_imported_repository(
    imported: list[ImportedSkill],
) -> list[tuple[Skill, SkillSnapshot, str]]:
    async with AsyncSessionLocal() as session:
        results: list[tuple[Skill, SkillSnapshot, str]] = []
        for item in imported:
            skill, snapshot = await add_skill(
                session,
                item.payload,
                preserve_catalog_state=True,
            )
            results.append((skill, snapshot, item.source_path))
        await session.commit()
    return results


async def import_github_from_args(args: argparse.Namespace) -> int:
    filters = github_repository_filters_from_args(args)
    requested_owner = filters.legacy_owners[0] if len(filters.legacy_owners) == 1 else ""
    raw_subfolder = str(getattr(args, "subfolder", "") or "")
    subfolder = validate_import_subfolder(raw_subfolder) if raw_subfolder else ""
    token = github_token_from_args(args)
    scope_label = filters.scope_label
    listed_repository_count = 0
    active_repository_count = 0
    matched_repository_count = 0
    imported_repository_count = 0
    skipped_repository_count = 0
    failed_repository_count = 0
    failed_skill_count = 0
    imported_skill_count = 0
    imported_bytes = 0
    owner_discovery_failed = False
    discovery_stats = GitHubDiscoveryStats(scope_label=scope_label)
    log_context: dict[str, object] = {
        "requested_owner": requested_owner or None,
        "scope": scope_label,
        "subfolder": subfolder,
        "repository_filters": {
            "min_stars": filters.min_stars,
            "max_stars": filters.max_stars,
            "pushed_after": filters.pushed_after,
            "pushed_before": filters.pushed_before,
            "created_after": filters.created_after,
            "created_before": filters.created_before,
            "language": filters.language,
            "topics": filters.topics,
            "verified_orgs_only": filters.verified_orgs_only,
            "max_repositories": filters.max_repositories,
        },
        "github_token_configured": bool(token),
    }
    logger.info("github skills import started", extra=log_context)

    def finish_import() -> int:
        effective_listed_count = max(
            listed_repository_count,
            discovery_stats.listed_repository_count,
        )
        effective_active_count = max(
            active_repository_count,
            discovery_stats.active_repository_count,
        )
        failed = (
            owner_discovery_failed
            or failed_repository_count > 0
            or failed_skill_count > 0
        )
        no_skills = imported_skill_count == 0
        logger.info(
            "github skills import completed",
            extra={
                **log_context,
                "scope": scope_label,
                "listed_repository_count": effective_listed_count,
                "active_repository_count": effective_active_count,
                "matched_repository_count": matched_repository_count,
                "imported_repository_count": imported_repository_count,
                "skipped_repository_count": skipped_repository_count,
                "failed_repository_count": failed_repository_count,
                "failed_skill_count": failed_skill_count,
                "owner_discovery_failed": owner_discovery_failed,
                "skill_count": imported_skill_count,
                "skill_bundle_bytes": imported_bytes,
                "search_request_count": discovery_stats.search_query_count,
            },
        )
        summary = (
            f"imported {imported_skill_count} skill(s) from "
            f"{imported_repository_count} of {effective_active_count} active GitHub "
            f"repositories for {scope_label}: {skipped_repository_count} repositories "
            f"skipped, {failed_repository_count} failed, {failed_skill_count} skills failed"
        )
        if owner_discovery_failed:
            summary = f"{summary}; owner discovery failed"
        print(summary)
        return 1 if failed or no_skills else 0

    async with GitHubClient(token=token, timeout_seconds=args.timeout_seconds) as client:
        iter_repositories = getattr(client, "iter_repositories", None)
        streaming_discovery = callable(iter_repositories)
        if streaming_discovery:
            repository_iterator = iter_repositories(filters, discovery_stats).__aiter__()
            logger.info("github skills import repository streaming started", extra=log_context)
        else:
            if len(filters.legacy_owners) != 1 or any(
                (
                    filters.organizations,
                    filters.users,
                    filters.repositories,
                    filters.all_github,
                )
            ):
                raise SkillCliError("GitHub client does not support filtered repository discovery")
            try:
                listing = await client.list_active_repositories(requested_owner)
            except (SkillCliError, httpx.RequestError) as exc:
                owner_discovery_failed = True
                logger.error(
                    "github skills import owner discovery failed",
                    extra={
                        **log_context,
                        "failure_reason": str(exc) or type(exc).__name__,
                    },
                )
                return finish_import()
            scope_label = listing.owner.login
            discovery_stats.scope_label = scope_label
            listed_repository_count = listing.listed_count
            active_repository_count = len(listing.repositories)
            discovery_stats.known_repository_count = active_repository_count
            logger.info(
                "github skills import repositories listed",
                extra={
                    **log_context,
                    "owner_type": listing.owner.account_type,
                    "owner_avatar_url_configured": bool(listing.owner.avatar_url),
                    "listed_repository_count": listed_repository_count,
                    "active_repository_count": active_repository_count,
                    "filtered_repository_count": listed_repository_count
                    - active_repository_count,
                },
            )

            async def listed_repositories() -> AsyncIterator[GitHubImportRepository]:
                for repository in listing.repositories:
                    yield repository

            repository_iterator = listed_repositories().__aiter__()

        repository_index = 0
        while True:
            try:
                candidate = await anext(repository_iterator)
            except StopAsyncIteration:
                break
            except (SkillCliError, httpx.RequestError) as exc:
                owner_discovery_failed = True
                logger.error(
                    "github skills import repository discovery failed",
                    extra={
                        **log_context,
                        "failure_reason": str(exc) or type(exc).__name__,
                    },
                )
                return finish_import()
            if streaming_discovery:
                listed_repository_count = discovery_stats.listed_repository_count
                active_repository_count = discovery_stats.active_repository_count
            current_repository_index = repository_index
            repository_index += 1
            repo = candidate.repo
            repo_context = {
                **log_context,
                "source": repo.source,
                "repository_url": repo.url,
                "requested_ref": candidate.default_branch,
            }
            if not candidate.default_branch:
                skipped_repository_count += 1
                logger.info(
                    "github skills import repository skipped",
                    extra={
                        **repo_context,
                        "skip_reason": "repository has no default branch",
                    },
                )
                continue

            try:
                metadata = await client.repository_metadata(repo)
                ref = metadata.default_branch
                repo_context["requested_ref"] = ref
                resolved_ref = await client.resolve_commit_sha(
                    repo,
                    ref,
                )
                tree = await client.recursive_tree(repo, resolved_ref)
            except (GitHubSystemicError, httpx.RequestError) as exc:
                failed_repository_count += (
                    active_repository_count - current_repository_index
                    if discovery_stats.known_repository_count is not None
                    else 1
                )
                logger.error(
                    "github skills import aborted",
                    extra={
                        **repo_context,
                        "failure_reason": str(exc) or type(exc).__name__,
                        "failed_repository_count": failed_repository_count,
                    },
                )
                return finish_import()
            except (GitHubTreeTruncatedError, SkillNotFoundError) as exc:
                skipped_repository_count += 1
                logger.info(
                    "github skills import repository skipped",
                    extra={
                        **repo_context,
                        "skip_reason": str(exc),
                    },
                )
                continue
            except SkillCliError as exc:
                failed_repository_count += 1
                logger.warning(
                    "github skills import repository failed",
                    extra={
                        **repo_context,
                        "failure_reason": str(exc),
                    },
                )
                continue

            logger.info(
                "github skills import repository resolved",
                extra={
                    **repo_context,
                    "ref": ref,
                    "resolved_ref": resolved_ref,
                    "tree_item_count": len(tree),
                },
            )
            try:
                skill_paths = discover_skill_paths(tree, subfolder=subfolder)
            except SkillNotFoundError as exc:
                skipped_repository_count += 1
                logger.info(
                    "github skills import repository skipped",
                    extra={
                        **repo_context,
                        "resolved_ref": resolved_ref,
                        "skip_reason": str(exc),
                    },
                )
                continue
            except SkillCliError as exc:
                failed_repository_count += 1
                logger.warning(
                    "github skills import repository failed",
                    extra={
                        **repo_context,
                        "resolved_ref": resolved_ref,
                        "failure_reason": str(exc),
                    },
                )
                continue

            matched_repository_count += 1
            logger.info(
                "github skills import discovered skills",
                extra={
                    **repo_context,
                    "resolved_ref": resolved_ref,
                    "skill_count": len(skill_paths),
                    "skill_paths": skill_paths[:MAX_LOGGED_SKILL_PATHS],
                    "skill_paths_truncated": len(skill_paths) > MAX_LOGGED_SKILL_PATHS,
                },
            )
            fetchable_skill_paths: list[str] = []
            bundle_items_by_path: dict[str, list[GitHubTreeItem]] = {}
            attempted_repository_bytes = 0
            repository_failed = False
            for skill_path in skill_paths:
                try:
                    bundle_items = skill_bundle_tree_items(
                        tree,
                        skill_path=skill_path,
                    )
                    attempted_repository_bytes = checked_github_import_size(
                        attempted_repository_bytes,
                        sum(item.size for item in bundle_items),
                    )
                except InvalidSkillBundleError as exc:
                    failed_skill_count += 1
                    logger.warning(
                        "github skill import skipped invalid skill",
                        extra={
                            **repo_context,
                            "resolved_ref": resolved_ref,
                            "source_path": skill_path,
                            "skip_reason": str(exc),
                        },
                    )
                    continue
                except SkillCliError as exc:
                    failed_repository_count += 1
                    repository_failed = True
                    logger.warning(
                        "github skills import repository failed",
                        extra={
                            **repo_context,
                            "resolved_ref": resolved_ref,
                            "source_path": skill_path,
                            "failure_reason": str(exc),
                        },
                    )
                    break
                bundle_items_by_path[skill_path] = bundle_items
                fetchable_skill_paths.append(skill_path)

            if repository_failed or not fetchable_skill_paths:
                continue
            imported: list[ImportedSkill] = []
            repository_bytes = 0
            for skill_path in fetchable_skill_paths:
                try:
                    imported_skill = await import_skill_from_github_path(
                        client=client,
                        repo=repo,
                        ref=ref,
                        tree=tree,
                        skill_path=skill_path,
                        fetch_ref=resolved_ref,
                        owner_avatar_url=metadata.owner_avatar_url
                        or candidate.owner_avatar_url,
                        import_subfolder=subfolder,
                        bundle_items=bundle_items_by_path[skill_path],
                    )
                    repository_bytes = checked_github_import_size(
                        repository_bytes,
                        imported_skill.bundle_size,
                    )
                except (InvalidSkillTextError, InvalidSkillBundleError) as exc:
                    failed_skill_count += 1
                    logger.warning(
                        "github skill import skipped invalid skill",
                        extra={
                            **repo_context,
                            "resolved_ref": resolved_ref,
                            "source_path": skill_path,
                            "skip_reason": str(exc),
                        },
                    )
                    continue
                except (GitHubSystemicError, httpx.RequestError) as exc:
                    failed_repository_count += (
                        active_repository_count - current_repository_index
                        if discovery_stats.known_repository_count is not None
                        else 1
                    )
                    logger.error(
                        "github skills import aborted",
                        extra={
                            **repo_context,
                            "resolved_ref": resolved_ref,
                            "source_path": skill_path,
                            "failure_reason": str(exc) or type(exc).__name__,
                            "failed_repository_count": failed_repository_count,
                        },
                    )
                    return finish_import()
                except SkillCliError as exc:
                    failed_repository_count += 1
                    repository_failed = True
                    logger.warning(
                        "github skills import repository failed",
                        extra={
                            **repo_context,
                            "resolved_ref": resolved_ref,
                            "source_path": skill_path,
                            "failure_reason": str(exc),
                        },
                    )
                    break
                imported.append(imported_skill)

            if repository_failed or not imported:
                continue
            try:
                validate_unique_imported_skill_slugs(imported)
                results = await save_imported_repository(imported)
            except SkillCliError as exc:
                failed_repository_count += 1
                logger.warning(
                    "github skills import repository failed",
                    extra={
                        **repo_context,
                        "resolved_ref": resolved_ref,
                        "failure_reason": str(exc),
                    },
                )
                continue
            except Exception:
                logger.exception(
                    "github skills import database failed",
                    extra={
                        **repo_context,
                        "resolved_ref": resolved_ref,
                    },
                )
                raise

            imported_repository_count += 1
            imported_skill_count += len(results)
            imported_bytes += repository_bytes
            for skill, snapshot, source_path in results:
                logger.info(
                    "github skill import saved skill",
                    extra={
                        **repo_context,
                        "resolved_ref": resolved_ref,
                        "skill_id": f"{skill.source}/{skill.slug}",
                        "source_path": source_path,
                        "snapshot_hash": snapshot.content_hash,
                    },
                )

        if streaming_discovery:
            listed_repository_count = discovery_stats.listed_repository_count
            active_repository_count = discovery_stats.active_repository_count
            logger.info(
                "github skills import repositories streamed",
                extra={
                    **log_context,
                    "listed_repository_count": listed_repository_count,
                    "active_repository_count": active_repository_count,
                    "filtered_repository_count": discovery_stats.filtered_repository_count,
                    "search_request_count": discovery_stats.search_query_count,
                },
            )

    return finish_import()


def log_github_refresh_failure(
    message: str,
    exc: Exception,
    *,
    context: dict[str, object],
) -> None:
    extra = {
        **context,
        "failure_reason": str(exc) or type(exc).__name__,
    }
    if isinstance(exc, SkillCliError):
        logger.warning(message, extra=extra)
    else:
        logger.exception(message, extra=extra)


async def refresh_github_from_args(args: argparse.Namespace) -> int:
    targets, provenance_issues = await load_skill_refresh_targets()
    token = github_token_from_args(args)
    total = len(targets) + len(provenance_issues)
    updated = 0
    unchanged = 0
    failed = len(provenance_issues)
    refreshed_bytes = 0
    logger.info(
        "github skills refresh started",
        extra={
            "skill_count": total,
            "refreshable_skill_count": len(targets),
            "github_token_configured": bool(token),
        },
    )
    for issue in provenance_issues:
        logger.warning(
            "github skill refresh failed",
            extra={
                "skill_id": issue.skill_id,
                "failure_stage": "provenance",
                "failure_reason": issue.reason,
            },
        )

    def finish_refresh() -> int:
        succeeded = updated + unchanged
        logger.info(
            "github skills refresh completed",
            extra={
                "skill_count": total,
                "refreshed_skill_count": succeeded,
                "updated_skill_count": updated,
                "unchanged_skill_count": unchanged,
                "failed_skill_count": failed,
                "skill_bundle_bytes": refreshed_bytes,
            },
        )
        print(
            f"refreshed {succeeded} of {total} GitHub skill(s): "
            f"{updated} updated, {unchanged} unchanged, {failed} failed"
        )
        return 1 if failed else 0

    def abort_refresh(exc: Exception) -> int:
        nonlocal failed
        failed = total - updated - unchanged
        logger.error(
            "github skills refresh aborted",
            extra={
                "failure_reason": str(exc) or type(exc).__name__,
                "failed_skill_count": failed,
            },
        )
        return finish_refresh()

    repository_groups: dict[str, list[SkillRefreshTarget]] = {}
    for target in targets:
        repository_groups.setdefault(target.repo.source.lower(), []).append(target)

    if targets:
        async with GitHubClient(token=token, timeout_seconds=args.timeout_seconds) as client:
            for repository_key in sorted(repository_groups):
                repository_targets = repository_groups[repository_key]
                repo = repository_targets[0].repo
                try:
                    metadata = await client.repository_metadata(repo)
                except (SkillCliError, httpx.RequestError) as exc:
                    log_github_refresh_failure(
                        "github skills refresh repository failed",
                        exc,
                        context={
                            "source": repo.source,
                            "skill_count": len(repository_targets),
                        },
                    )
                    if isinstance(exc, (GitHubSystemicError, httpx.RequestError)):
                        return abort_refresh(exc)
                    failed += len(repository_targets)
                    continue

                ref_groups: dict[str, list[SkillRefreshTarget]] = {}
                for target in repository_targets:
                    requested_ref = target.ref or metadata.default_branch
                    ref_groups.setdefault(requested_ref, []).append(target)
                for requested_ref in sorted(ref_groups):
                    ref_targets = ref_groups[requested_ref]
                    try:
                        resolved_ref = await client.resolve_commit_sha(repo, requested_ref)
                        tree = await client.recursive_tree(repo, resolved_ref)
                    except (SkillCliError, httpx.RequestError) as exc:
                        log_github_refresh_failure(
                            "github skills refresh tree failed",
                            exc,
                            context={
                                "source": repo.source,
                                "requested_ref": requested_ref,
                                "skill_count": len(ref_targets),
                            },
                        )
                        if isinstance(exc, (GitHubSystemicError, httpx.RequestError)):
                            return abort_refresh(exc)
                        failed += len(ref_targets)
                        continue

                    logger.info(
                        "github skills refresh repository resolved",
                        extra={
                            "source": repo.source,
                            "requested_ref": requested_ref,
                            "resolved_ref": resolved_ref,
                            "tree_item_count": len(tree),
                            "skill_count": len(ref_targets),
                        },
                    )
                    for target in ref_targets:
                        try:
                            skill_md, files, bundle_size = await fetch_skill_bundle(
                                client=client,
                                repo=repo,
                                ref=resolved_ref,
                                tree=tree,
                                skill_path=target.skill_path,
                            )
                        except (SkillCliError, httpx.RequestError) as exc:
                            log_github_refresh_failure(
                                "github skill refresh failed",
                                exc,
                                context={
                                    "skill_id": target.id,
                                    "source": target.source,
                                    "source_path": target.skill_path,
                                    "requested_ref": requested_ref,
                                    "resolved_ref": resolved_ref,
                                    "failure_stage": "fetch",
                                },
                            )
                            if isinstance(exc, (GitHubSystemicError, httpx.RequestError)):
                                return abort_refresh(exc)
                            failed += 1
                            continue

                        try:
                            snapshot_hash, changed = await save_refreshed_skill(
                                target,
                                skill_md=skill_md,
                                files=files,
                            )
                        except SkillCliError as exc:
                            failed += 1
                            log_github_refresh_failure(
                                "github skill refresh failed",
                                exc,
                                context={
                                    "skill_id": target.id,
                                    "source": target.source,
                                    "source_path": target.skill_path,
                                    "requested_ref": requested_ref,
                                    "resolved_ref": resolved_ref,
                                    "failure_stage": "database",
                                },
                            )
                            continue

                        if changed:
                            updated += 1
                        else:
                            unchanged += 1
                        refreshed_bytes += bundle_size
                        logger.info(
                            "github skill refresh completed",
                            extra={
                                "skill_id": target.id,
                                "source": target.source,
                                "source_path": target.skill_path,
                                "requested_ref": requested_ref,
                                "resolved_ref": resolved_ref,
                                "snapshot_hash": snapshot_hash,
                                "snapshot_changed": changed,
                                "audit_refresh_required": changed,
                                "skill_file_count": len(files),
                                "skill_bundle_bytes": bundle_size,
                            },
                        )

    return finish_refresh()


async def mark_official_from_args(args: argparse.Namespace) -> int:
    owner = validate_skill_owner(args.owner)
    source_type = args.source_type
    official = not args.unset
    owner_url = (args.owner_url or "").strip()
    owner_icon_url = (args.owner_icon_url or "").strip()
    if not owner_url and source_type == "github":
        owner_url = github_owner_url(owner)

    async with AsyncSessionLocal() as session:
        if not owner_icon_url:
            skill_result = await session.execute(
                select(Skill.source_owner_icon_url).where(
                    Skill.source_type == source_type,
                    Skill.source_owner.ilike(owner),
                    Skill.source_owner_icon_url != "",
                )
            )
            owner_icon_url = skill_result.scalars().first() or ""

        result = await session.execute(
            select(SkillSourceOwner).where(
                SkillSourceOwner.source_type == source_type,
                SkillSourceOwner.source_owner.ilike(owner),
            )
        )
        source_owner = result.scalar_one_or_none()
        if source_owner is None:
            source_owner = SkillSourceOwner(
                source_type=source_type,
                source_owner=owner,
                source_owner_url=owner_url,
                source_owner_icon_url=owner_icon_url,
                is_official=official,
            )
            session.add(source_owner)
        else:
            source_owner.source_owner = owner
            if owner_url:
                source_owner.source_owner_url = owner_url
            if owner_icon_url:
                source_owner.source_owner_icon_url = owner_icon_url
            source_owner.is_official = official

        await session.commit()
    action = "official" if official else "not official"
    print(f"marked {source_type} owner {owner} as {action}")
    return 0


def add_import_github_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "owner",
        nargs="?",
        type=github_owner_argument,
        help="Optional legacy GitHub user or organization login.",
    )
    parser.add_argument(
        "--owner",
        dest="owners",
        action="append",
        default=[],
        type=github_owner_argument,
        help="Auto-detected GitHub user or organization. Repeat to target several owners.",
    )
    parser.add_argument(
        "--org",
        dest="organizations",
        action="append",
        default=[],
        type=github_owner_argument,
        help="GitHub organization to search. Repeat to target several organizations.",
    )
    parser.add_argument(
        "--user",
        dest="users",
        action="append",
        default=[],
        type=github_owner_argument,
        help="GitHub user to search. Repeat to target several users.",
    )
    parser.add_argument(
        "--repo",
        dest="repositories",
        action="append",
        default=[],
        type=github_repository_argument,
        help="GitHub repository in owner/repo form. Repeat to target several repositories.",
    )
    parser.add_argument(
        "--all-github",
        action="store_true",
        help="Search all public GitHub repositories matching the supplied filters.",
    )
    parser.add_argument(
        "--subfolder",
        default=None,
        type=import_subfolder_argument,
        help=(
            "Repository subfolder containing SKILL.md. "
            "When omitted, only the repository root SKILL.md is imported."
        ),
    )
    parser.add_argument(
        "--min-stars",
        type=nonnegative_int_argument,
        help="Only repositories with at least this many stars.",
    )
    parser.add_argument(
        "--max-stars",
        type=nonnegative_int_argument,
        help="Only repositories with at most this many stars.",
    )
    parser.add_argument(
        "--active-within-days",
        type=positive_int_argument,
        help="Only repositories pushed to within this many days.",
    )
    parser.add_argument(
        "--pushed-after",
        type=github_timestamp_argument,
        default=None,
        help="Only repositories pushed on or after this ISO-8601 date or datetime.",
    )
    parser.add_argument(
        "--pushed-before",
        type=github_timestamp_argument,
        default=None,
        help="Only repositories pushed on or before this ISO-8601 date or datetime.",
    )
    parser.add_argument(
        "--created-after",
        type=github_timestamp_argument,
        default=None,
        help="Only repositories created on or after this ISO-8601 date or datetime.",
    )
    parser.add_argument(
        "--created-before",
        type=github_timestamp_argument,
        default=None,
        help="Only repositories created on or before this ISO-8601 date or datetime.",
    )
    parser.add_argument(
        "--language",
        type=github_language_argument,
        default=None,
        help="Only repositories whose primary language matches this value.",
    )
    parser.add_argument(
        "--topic",
        dest="topics",
        action="append",
        default=[],
        type=github_topic_argument,
        help="Required GitHub repository topic. Repeat to require several topics.",
    )
    parser.add_argument(
        "--verified-orgs-only",
        action="store_true",
        help="Only import repositories owned by GitHub-verified organizations.",
    )
    parser.add_argument(
        "--max-repositories",
        type=positive_int_argument,
        help="Stop after this many matching active repositories.",
    )
    parser.add_argument(
        "--github-token",
        default="",
        help=f"GitHub token. Defaults to ${GITHUB_TOKEN_ENV} when set.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_IMPORT_TIMEOUT_SECONDS,
        help="GitHub request timeout in seconds.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli.skills")
    subparsers = parser.add_subparsers(dest="command")
    add_parser = subparsers.add_parser("add", help="Add or update a skill from a local SKILL.md.")
    add_parser.add_argument("--source", required=True, help="GitHub source in owner/repo form.")
    add_parser.add_argument(
        "--skill-file",
        default="SKILL.md",
        help="Path to the local SKILL.md file. Defaults to ./SKILL.md.",
    )
    add_parser.add_argument("--slug", default="", help="Skill slug. Defaults from name.")
    add_parser.add_argument("--name", default="", help="Skill display name.")
    add_parser.add_argument("--description", default="", help="Skill description.")
    add_parser.add_argument(
        "--source-type",
        default="github",
        choices=["github", "well-known"],
        help="Skill source type.",
    )
    add_parser.add_argument("--source-owner", default="", help="Source owner, org, or publisher.")
    add_parser.add_argument("--source-name", default="", help="Source repository or package name.")
    add_parser.add_argument("--source-owner-url", default="", help="Source owner URL.")
    add_parser.add_argument("--source-owner-icon-url", default="", help="Source owner icon URL.")
    add_parser.add_argument("--source-url", default="", help="Source URL.")
    add_parser.add_argument("--install-url", default="", help="Install/source URL.")
    add_parser.add_argument("--website-url", default="", help="Website or docs URL.")
    add_parser.add_argument("--repository-url", default="", help="Repository URL.")
    import_parser = subparsers.add_parser(
        "import-github",
        help="Search and stream matching GitHub repositories into the skills catalog.",
    )
    add_import_github_arguments(import_parser)
    refresh_parser = subparsers.add_parser(
        "refresh",
        help=(
            "Refresh snapshot bundles for all active GitHub skills from their recorded "
            "repository locations."
        ),
    )
    refresh_parser.add_argument(
        "--github-token",
        default="",
        help=f"GitHub token override. Defaults to ${GITHUB_TOKEN_ENV} when set.",
    )
    refresh_parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_IMPORT_TIMEOUT_SECONDS,
        help="GitHub request timeout in seconds.",
    )
    official_parser = subparsers.add_parser(
        "mark-official",
        help="Mark a source owner as official.",
    )
    official_parser.add_argument("owner", help="Skill owner, for example vercel-labs.")
    official_parser.add_argument(
        "--source-type",
        default="github",
        choices=["github", "well-known"],
        help="Skill source type.",
    )
    official_parser.add_argument("--owner-url", default="", help="Official owner URL.")
    official_parser.add_argument("--owner-icon-url", default="", help="Official owner icon URL.")
    official_parser.add_argument(
        "--unset",
        action="store_true",
        help="Remove official status from the source owner.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "add":
        try:
            return asyncio.run(add_skill_from_args(args))
        except SkillCliError as exc:
            parser.error(str(exc))
    if args.command == "import-github":
        try:
            configure_logging()
            return asyncio.run(import_github_from_args(args))
        except SkillCliError as exc:
            parser.error(str(exc))
    if args.command == "refresh":
        try:
            configure_logging()
            return asyncio.run(refresh_github_from_args(args))
        except SkillCliError as exc:
            parser.error(str(exc))
    if args.command == "mark-official":
        try:
            return asyncio.run(mark_official_from_args(args))
        except SkillCliError as exc:
            parser.error(str(exc))
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
