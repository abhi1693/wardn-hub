from __future__ import annotations

import argparse
import asyncio
import base64
import codecs
import fnmatch
import hashlib
import json
import logging
import os
import re
import sys
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Literal, NotRequired, TypedDict
from urllib.parse import quote, unquote, urlparse

import httpx
import yaml
from ftfy import fix_encoding
from markdown_it import MarkdownIt
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal, engine
from app.modules.skills.models import (
    GitHubHttpCache,
    Skill,
    SkillAudit,
    SkillSnapshot,
    SkillSourceOwner,
)

logger = logging.getLogger(__name__)

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
GITHUB_OWNER_PATTERN = re.compile(r"^(?!.*--)[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
GITHUB_IMPORT_OUTPUT_FORMATS = ("json", "text")
GITHUB_API_ROOT = "https://api.github.com"
GITHUB_REPOSITORIES_PER_PAGE = 100
GITHUB_SEARCH_RESULT_LIMIT = 1000
GITHUB_VERIFIED_ORG_CACHE_SIZE = 1024
GITHUB_CREATED_AT_FLOOR = datetime(1970, 1, 1, tzinfo=UTC)
GITHUB_RATE_LIMIT_WAIT_BUFFER_SECONDS = 1.0
GITHUB_SECONDARY_RATE_LIMIT_WAIT_SECONDS = 60.0
GITHUB_SECONDARY_RATE_LIMIT_MAX_WAIT_SECONDS = 15 * 60.0
GITHUB_RATE_LIMIT_MAX_RETRIES = 5
GITHUB_TRANSIENT_RETRY_BASE_SECONDS = 1.0
GITHUB_TRANSIENT_RETRY_MAX_SECONDS = 8.0
GITHUB_TRANSIENT_MAX_RETRIES = 3
GITHUB_DATABASE_RETRY_BASE_SECONDS = 1.0
GITHUB_DATABASE_RETRY_MAX_SECONDS = 8.0
GITHUB_DATABASE_MAX_RETRIES = 5
GITHUB_ETAG_CACHE_MAX_ENTRIES = 4096
GITHUB_ETAG_CACHE_MAX_BYTES = 64 * 1024 * 1024
GITHUB_ETAG_CACHE_MAX_ENTRY_BYTES = 2 * 1024 * 1024
GITHUB_NOT_MODIFIED_RESPONSE_HEADERS = {
    "etag",
    "last-modified",
    "x-github-request-id",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "x-ratelimit-resource",
    "x-ratelimit-used",
}
GITHUB_ERROR_BODY_MAX_CHARS = 1000
DEFAULT_USER_AGENT = "WardnHubSkillsImporter/0.1"
DEFAULT_IMPORT_TIMEOUT_SECONDS = 20.0
MAX_LOGGED_SKILL_PATHS = 20
MAX_SKILL_SLUG_LENGTH = 200
MAX_SKILL_BUNDLE_FILES = 256
MAX_SKILL_FILE_BYTES = 8 * 1024 * 1024
MAX_SKILL_BUNDLE_BYTES = 16 * 1024 * 1024
MAX_SKILL_PATH_CHARS = 1024
MAX_SKILL_PATH_PARTS = 64
MAX_BUNDLE_FETCH_CONCURRENCY = 8
MAX_GITHUB_IMPORT_BYTES = 256 * 1024 * 1024
WINDOWS_1252_EM_DASH_BYTE = b"\x97"
WINDOWS_1252_EM_DASH_SENTINEL = "\udc97"
GITHUB_TEXT_DECODE_ERRORS = "wardn_github_text_decode"
KNOWN_GITHUB_TEXT_MOJIBAKE_REPLACEMENTS = (
    (
        "\u00f0\u0178\u00c2\u008f\u20ac\u00ba\u00ef\u00b8\u008f",
        "\N{AMPHORA}\N{VARIATION SELECTOR-16}",
    ),
    (
        "\u201e\u00b9\u00ef\u00b8\u008f",
        "\N{INFORMATION SOURCE}\N{VARIATION SELECTOR-16}",
    ),
)
SKILL_BUNDLE_FORMAT_VERSION = 2
MAX_SKILL_RESOLUTION_ISSUES = 128
MAX_SKILL_DEPENDENCY_MANIFEST_ENTRIES = 512
SKIPPED_PATH_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "vendor",
}
MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
INLINE_CODE_PATTERN = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
REFERENCE_DIRECTIVE_PATTERN = re.compile(
    r"\b(?:read|see|open|load|follow|consult|review|inspect|include|import|use)\b",
    re.IGNORECASE,
)
OPTIONAL_REFERENCE_PATTERN = re.compile(
    r"\b(?:optional|optionally|example|examples|if available|when available|if present|"
    r"if (?:it|they) exists?)\b",
    re.IGNORECASE,
)
RUNTIME_OUTPUT_PATTERN = re.compile(
    r"\b(?:create|write|generate|save|output|emit|export|produce)\b",
    re.IGNORECASE,
)
LOCAL_PATH_CANDIDATE_PATTERN = re.compile(
    r"^(?:\.\.?/)?[^\s`]+(?:/[^\s`]+)*(?:\.[A-Za-z0-9_-]{1,24}|/|[*?\[])$"
)
NON_PATH_REFERENCE_LITERALS = {"e.g", "i.e"}
PLAIN_LOCAL_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:\.\.?/)?(?:[A-Za-z0-9._*?\[\]-]+/)*"
    r"[A-Za-z0-9._*?\[\]-]+(?:\.[A-Za-z0-9_-]{1,24}|/)"
)
WINDOWS_RESERVED_PATH_PATTERN = re.compile(
    r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.IGNORECASE
)
MARKDOWN = MarkdownIt("commonmark")


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


class GitHubImportTextFormatter(logging.Formatter):
    fields = (
        "source",
        "skill_id",
        "source_path",
        "normalized_byte_count",
        "normalized_control_count",
        "reason",
        "response_status_code",
        "github_request_id",
        "request_host",
        "request_path",
        "rate_limit_reason",
        "rate_limit_resource",
        "rate_limit_remaining",
        "rate_limit_reset",
        "retry_attempt",
        "retry_wait_seconds",
        "imported_skill_count",
        "failed_skill_count",
        "skipped_repository_count",
    )
    labeled_fields = {
        "response_status_code": "status",
        "github_request_id": "request_id",
        "request_host": "host",
        "request_path": "path",
        "rate_limit_reason": "limit",
        "rate_limit_resource": "resource",
        "rate_limit_remaining": "remaining",
        "rate_limit_reset": "reset_epoch",
        "retry_attempt": "attempt",
        "retry_wait_seconds": "wait_seconds",
        "source_path": "path",
        "normalized_byte_count": "normalized_bytes",
        "normalized_control_count": "normalized_controls",
    }

    def formatTime(
        self,
        record: logging.LogRecord,
        datefmt: str | None = None,
    ) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        return f"{timestamp},{int(record.msecs):03d}"

    def format(self, record: logging.LogRecord) -> str:
        values: list[object] = [
            self.formatTime(record),
            record.levelname,
            record.getMessage(),
        ]
        for field in self.fields:
            if field == "reason":
                value = getattr(
                    record,
                    "skip_reason",
                    getattr(record, "failure_reason", ""),
                )
            else:
                value = getattr(record, field, "")
            if value != "":
                label = self.labeled_fields.get(field)
                values.append(f"{label}={value}" if label else value)
        return "\t".join(str(value) for value in values if value != "")


def configure_github_import_output(output: str) -> None:
    if output != "text":
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(GitHubImportTextFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = True
    logger.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)


SkillFileEncoding = Literal["utf-8", "base64"]


class SkillSnapshotFile(TypedDict):
    path: str
    contents: str
    encoding: NotRequired[SkillFileEncoding]
    executable: NotRequired[bool]


SkillResolutionStatus = Literal["complete", "incomplete", "pending"]


class SkillResolutionIssue(TypedDict):
    sourcePath: str
    target: str
    reason: str
    required: bool


class SkillDependencyManifestEntry(TypedDict):
    sourcePath: str
    target: str
    kind: str
    required: bool
    resolvedPaths: list[str]


@dataclass(frozen=True)
class FetchedSkillBundle:
    source_skill_md: str
    skill_md: str
    files: list[SkillSnapshotFile]
    bundle_size: int
    bundle_format_version: int
    source_commit_sha: str
    source_entrypoint: str
    resolution_status: SkillResolutionStatus
    resolution_issues: list[SkillResolutionIssue]
    dependency_manifest: list[SkillDependencyManifestEntry]


@dataclass(frozen=True)
class LocalDependencyReference:
    target: str
    required: bool
    kind: str


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
    repository_subfolder: str | None = None
    repository_ref: str = ""
    bundle_format_version: int = SKILL_BUNDLE_FORMAT_VERSION
    source_commit_sha: str = ""
    source_entrypoint: str = "SKILL.md"
    resolution_status: SkillResolutionStatus = "complete"
    resolution_issues: list[SkillResolutionIssue] = dataclass_field(default_factory=list)
    dependency_manifest: list[SkillDependencyManifestEntry] = dataclass_field(default_factory=list)


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
    created_at: str = ""
    disabled: bool = False
    language: str = ""
    pushed_at: str = ""
    stargazers_count: int = 0
    topics: tuple[str, ...] = ()


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
    repository_names: tuple[str, ...] = ()
    excluded_organizations: tuple[str, ...] = ()
    excluded_users: tuple[str, ...] = ()
    excluded_existing_owners: frozenset[str] = frozenset()
    excluded_repositories: tuple[str, ...] = ()
    excluded_repository_names: tuple[str, ...] = ()
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
class GitHubCodeSearchPage:
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
class PlannedSkillImport:
    skill_path: str
    slug: str


@dataclass(frozen=True)
class SavedImportedSkill:
    source: str
    slug: str
    source_path: str
    content_hash: str | None

    @property
    def skill_id(self) -> str:
        return f"{self.source}/{self.slug}"


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


@dataclass(frozen=True)
class GitHubRateLimitBudget:
    remaining: int
    reset_epoch_seconds: float


@dataclass(frozen=True)
class GitHubETagCacheEntry:
    cache_key: str
    etag: str
    response_headers: dict[str, str]
    body: bytes
    last_accessed_at: datetime


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
        except (TypeError, ValueError):
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
    exponential_wait = GITHUB_SECONDARY_RATE_LIMIT_WAIT_SECONDS * (2 ** min(retry_attempt, 4))
    return GitHubRateLimitWait(
        seconds=min(exponential_wait, GITHUB_SECONDARY_RATE_LIMIT_MAX_WAIT_SECONDS),
        reason="secondary",
    )


def github_transient_retry_wait(retry_attempt: int) -> float:
    return min(
        GITHUB_TRANSIENT_RETRY_BASE_SECONDS * (2**retry_attempt),
        GITHUB_TRANSIENT_RETRY_MAX_SECONDS,
    )


def github_rate_limit_resource_for_request(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.hostname != "api.github.com":
        return None
    if parsed.path == "/search/code":
        return "code_search"
    if parsed.path.startswith("/search/"):
        return "search"
    return "core"


def github_rate_limit_budget(
    response: object,
    *,
    fallback_resource: str | None,
) -> tuple[str, GitHubRateLimitBudget] | None:
    resource = github_response_header(response, "x-ratelimit-resource") or fallback_resource
    remaining = github_response_header(response, "x-ratelimit-remaining")
    reset = github_response_header(response, "x-ratelimit-reset")
    if not resource or remaining is None or reset is None:
        return None
    try:
        remaining_value = int(remaining)
        reset_value = float(reset)
    except (TypeError, ValueError):
        return None
    if remaining_value < 0 or reset_value < 0:
        return None
    return resource, GitHubRateLimitBudget(
        remaining=remaining_value,
        reset_epoch_seconds=reset_value,
    )


def github_etag_cache_key(
    *,
    token_scope: str,
    url: str,
    params: dict[str, str] | None,
) -> str | None:
    if urlparse(url).hostname != "api.github.com" or not token_scope:
        return None
    query = str(httpx.QueryParams(sorted((params or {}).items())))
    material = f"{token_scope}\0{url}\0{query}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def github_cacheable_response_headers(response: object) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name in ("content-type", "etag", "last-modified"):
        value = github_response_header(response, name)
        if value:
            headers[name] = value
    return headers


async def load_github_etag_cache() -> dict[str, GitHubETagCacheEntry]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(GitHubHttpCache)
            .order_by(GitHubHttpCache.last_accessed_at.desc())
            .limit(GITHUB_ETAG_CACHE_MAX_ENTRIES)
        )
        rows = result.scalars().all()
    entries: dict[str, GitHubETagCacheEntry] = {}
    total_bytes = 0
    for row in rows:
        if row.body_bytes != len(row.body) or row.body_bytes > GITHUB_ETAG_CACHE_MAX_ENTRY_BYTES:
            continue
        if total_bytes + row.body_bytes > GITHUB_ETAG_CACHE_MAX_BYTES:
            break
        entries[row.cache_key] = GitHubETagCacheEntry(
            cache_key=row.cache_key,
            etag=row.etag,
            response_headers=dict(row.response_headers),
            body=row.body,
            last_accessed_at=row.last_accessed_at,
        )
        total_bytes += row.body_bytes
    return entries


async def persist_github_etag_cache(entries: list[GitHubETagCacheEntry]) -> None:
    if not entries:
        return
    values = [
        {
            "cache_key": entry.cache_key,
            "etag": entry.etag,
            "response_headers": entry.response_headers,
            "body": entry.body,
            "body_bytes": len(entry.body),
            "last_accessed_at": entry.last_accessed_at,
        }
        for entry in entries
    ]
    statement = postgresql_insert(GitHubHttpCache).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=[GitHubHttpCache.cache_key],
        set_={
            "etag": statement.excluded.etag,
            "response_headers": statement.excluded.response_headers,
            "body": statement.excluded.body,
            "body_bytes": statement.excluded.body_bytes,
            "last_accessed_at": statement.excluded.last_accessed_at,
        },
    )
    async with AsyncSessionLocal() as session:
        await session.execute(statement)
        rows = (
            await session.execute(
                select(
                    GitHubHttpCache.cache_key,
                    GitHubHttpCache.body_bytes,
                ).order_by(GitHubHttpCache.last_accessed_at.desc())
            )
        ).all()
        retained_bytes = 0
        expired_keys: list[str] = []
        for index, (cache_key, body_bytes) in enumerate(rows):
            retained_bytes += body_bytes
            if (
                index >= GITHUB_ETAG_CACHE_MAX_ENTRIES
                or retained_bytes > GITHUB_ETAG_CACHE_MAX_BYTES
            ):
                expired_keys.append(cache_key)
        if expired_keys:
            await session.execute(
                delete(GitHubHttpCache).where(GitHubHttpCache.cache_key.in_(expired_keys))
            )
        await session.commit()


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


def github_text_decode_error(error: UnicodeError) -> tuple[str, int]:
    if (
        not isinstance(error, UnicodeDecodeError)
        or error.encoding != "utf-8"
        or error.object[error.start : error.end] != WINDOWS_1252_EM_DASH_BYTE
    ):
        raise error
    return WINDOWS_1252_EM_DASH_SENTINEL, error.end


codecs.register_error(GITHUB_TEXT_DECODE_ERRORS, github_text_decode_error)


def normalize_github_text_mojibake(contents: str) -> tuple[str, int]:
    c1_control_count = sum(127 <= ord(character) <= 159 for character in contents)
    if not c1_control_count:
        return contents, 0

    normalized = contents
    for corrupted, replacement in KNOWN_GITHUB_TEXT_MOJIBAKE_REPLACEMENTS:
        normalized = normalized.replace(corrupted, replacement)
    normalized = fix_encoding(normalized)
    normalized = re.sub(
        "\u00c2([\u0080-\u009f])",
        lambda match: match.group(1),
        normalized,
    )
    normalized = fix_encoding(normalized)
    if normalized == contents or unsupported_text_control(normalized) is not None:
        return contents, 0
    return normalized, c1_control_count


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
    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration:
        return {}
    try:
        value = yaml.safe_load("\n".join(lines[1:closing_index]))
    except yaml.YAMLError:
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item.strip()
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str) and item.strip()
    }


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
    if not repository or len(repository) > 100 or not re.fullmatch(r"[A-Za-z0-9_.-]+", repository):
        raise argparse.ArgumentTypeError(
            "repository name may contain letters, numbers, dots, hyphens, and underscores"
        )
    return f"{owner}/{repository}"


def github_repository_name_argument(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 100 or not re.fullmatch(r"[A-Za-z0-9_.-]+", normalized):
        raise argparse.ArgumentTypeError(
            "repository name match may contain letters, numbers, dots, hyphens, and underscores"
        )
    return normalized


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
    excluded_organizations = unique_casefolded(
        [
            validate_github_owner(owner)
            for owner in (getattr(args, "excluded_organizations", []) or [])
        ]
    )
    excluded_users = unique_casefolded(
        [validate_github_owner(owner) for owner in (getattr(args, "excluded_users", []) or [])]
    )
    raw_excluded_repositories = list(getattr(args, "excluded_repositories", []) or [])
    excluded_repositories = unique_casefolded(
        [github_repository_argument(repository) for repository in raw_excluded_repositories]
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
            (datetime.now(tz=UTC) - timedelta(days=active_within_days)).date().isoformat()
        )
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
        repository_names=unique_casefolded(list(getattr(args, "repository_names", []) or [])),
        excluded_organizations=excluded_organizations,
        excluded_users=excluded_users,
        excluded_repositories=excluded_repositories,
        excluded_repository_names=unique_casefolded(
            list(getattr(args, "excluded_repository_names", []) or [])
        ),
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
    if payload.repository_subfolder is not None:
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
    bundle_format_version: int = SKILL_BUNDLE_FORMAT_VERSION,
    source_commit_sha: str = "",
    source_entrypoint: str = "SKILL.md",
    resolution_status: SkillResolutionStatus = "complete",
    resolution_issues: list[SkillResolutionIssue] | None = None,
    dependency_manifest: list[SkillDependencyManifestEntry] | None = None,
) -> SkillSnapshot:
    hash_value = content_hash(files)
    frontmatter = parse_frontmatter(skill_md)
    previous_snapshot_id = skill.current_snapshot_id
    await session.execute(select(Skill.id).where(Skill.id == skill.id).with_for_update())
    await session.execute(
        update(SkillSnapshot).where(SkillSnapshot.skill_id == skill.id).values(is_latest=False)
    )
    result = await session.execute(
        select(SkillSnapshot).where(
            SkillSnapshot.skill_id == skill.id,
            SkillSnapshot.content_hash == hash_value,
        )
    )
    snapshot = result.scalar_one_or_none()
    resolution_changed = False
    if snapshot is None:
        snapshot = SkillSnapshot(
            skill_id=skill.id,
            content_hash=hash_value,
            skill_md=skill_md,
            metadata_=frontmatter,
            files=files,
            bundle_format_version=bundle_format_version,
            source_commit_sha=source_commit_sha,
            source_entrypoint=source_entrypoint,
            resolution_status=resolution_status,
            resolution_issues=resolution_issues or [],
            dependency_manifest=dependency_manifest or [],
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
        resolution_changed = (
            snapshot.bundle_format_version != bundle_format_version
            or snapshot.source_entrypoint != source_entrypoint
            or snapshot.resolution_status != resolution_status
            or snapshot.resolution_issues != (resolution_issues or [])
            or snapshot.dependency_manifest != (dependency_manifest or [])
        )
        snapshot.bundle_format_version = bundle_format_version
        snapshot.source_commit_sha = source_commit_sha
        snapshot.source_entrypoint = source_entrypoint
        snapshot.resolution_status = resolution_status
        snapshot.resolution_issues = resolution_issues or []
        snapshot.dependency_manifest = dependency_manifest or []
        snapshot.status = "active"
        snapshot.is_latest = True

    if (previous_snapshot_id is not None and previous_snapshot_id != snapshot.id) or (
        resolution_changed
    ):
        await session.execute(delete(SkillAudit).where(SkillAudit.skill_id == skill.id))
    skill.current_snapshot_id = snapshot.id
    return snapshot


async def add_skill(
    session: AsyncSession,
    payload: SkillAddInput,
    *,
    preserve_catalog_state: bool = False,
) -> tuple[Skill, SkillSnapshot]:
    if payload.resolution_status != "complete":
        raise SkillCliError(
            f"refusing to store {payload.resolution_status} skill package: "
            f"{payload.source}/{payload.slug}"
        )
    if payload.source_type == "github":
        owner_lock_key = f"wardn-hub:github-owner:{payload.source_owner.casefold()}"
        await session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(owner_lock_key, 0)))
        )
    source_filter = Skill.source == payload.source
    if payload.source_type == "github":
        source_filter = func.lower(Skill.source) == payload.source.lower()
    skill: Skill | None = None
    has_repository_identity = (
        preserve_catalog_state
        and payload.source_type == "github"
        and payload.repository_subfolder is not None
    )
    if has_repository_identity:
        result = await session.execute(
            select(Skill).where(
                Skill.source_type == payload.source_type,
                source_filter,
                Skill.repository_subfolder == payload.repository_subfolder,
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
        if skill is not None and has_repository_identity:
            existing_subfolder = skill.repository_subfolder
            if existing_subfolder != payload.repository_subfolder:
                skill_path = (
                    f"{payload.repository_subfolder}/SKILL.md"
                    if payload.repository_subfolder
                    else "SKILL.md"
                )
                collision_slug = repository_collision_slug(payload.slug, skill_path)
                result = await session.execute(
                    select(Skill).where(
                        Skill.source_type == payload.source_type,
                        source_filter,
                        Skill.slug == collision_slug,
                    )
                )
                collision_owner = result.scalar_one_or_none()
                if collision_owner is not None:
                    raise SkillCliError(
                        f"deterministic skill slug {collision_slug} is already in use"
                    )
                payload = replace(payload, slug=collision_slug)
                skill = None
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
            repository_subfolder=payload.repository_subfolder,
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
        if payload.repository_subfolder is not None:
            skill.repository_subfolder = payload.repository_subfolder
        if not preserve_catalog_state:
            skill.status = "active"
            skill.visibility = "public"

    snapshot = await upsert_skill_snapshot(
        session,
        skill,
        skill_md=payload.skill_md,
        files=payload.files,
        bundle_format_version=payload.bundle_format_version,
        source_commit_sha=payload.source_commit_sha,
        source_entrypoint=payload.source_entrypoint,
        resolution_status=payload.resolution_status,
        resolution_issues=payload.resolution_issues,
        dependency_manifest=payload.dependency_manifest,
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
    qualifiers = [*filters.repository_names, "is:public", "archived:false"]
    if target.qualifier:
        qualifiers.append(f"{target.qualifier}:{target.value}")
    if filters.repository_names:
        qualifiers.append("in:name")
    qualifiers.extend(f"-org:{owner}" for owner in filters.excluded_organizations)
    qualifiers.extend(f"-user:{owner}" for owner in filters.excluded_users)
    qualifiers.extend(f"-repo:{repository}" for repository in filters.excluded_repositories)
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
        f"created:{github_search_timestamp(created_start)}..{github_search_timestamp(created_end)}"
    )
    return " ".join(qualifiers)


def github_skill_code_search_query(
    target: GitHubSearchTarget,
    *,
    recursive: bool,
    subfolder: str,
) -> str:
    qualifiers = ["filename:SKILL.md"]
    if target.qualifier:
        qualifiers.append(f"{target.qualifier}:{target.value}")
    if subfolder:
        qualifiers.append(f"path:{subfolder}")
    elif not recursive:
        qualifiers.append("path:/")
    return " ".join(qualifiers)


def github_skill_repository_code_search_query(
    repo: GitHubRepository,
    *,
    recursive: bool,
    subfolder: str,
) -> str:
    return github_skill_code_search_query(
        GitHubSearchTarget(qualifier="repo", value=repo.source),
        recursive=recursive,
        subfolder=subfolder,
    )


def github_metadata_matches_filters(
    metadata: GitHubRepositoryMetadata,
    filters: GitHubRepositoryFilters,
) -> bool:
    if filters.min_stars is not None and metadata.stargazers_count < filters.min_stars:
        return False
    if filters.max_stars is not None and metadata.stargazers_count > filters.max_stars:
        return False
    if filters.pushed_after and metadata.pushed_at:
        pushed_at = parse_github_datetime(metadata.pushed_at, upper_bound=False)
        if pushed_at < parse_github_datetime(filters.pushed_after, upper_bound=False):
            return False
    if filters.pushed_before and metadata.pushed_at:
        pushed_at = parse_github_datetime(metadata.pushed_at, upper_bound=False)
        if pushed_at > parse_github_datetime(filters.pushed_before, upper_bound=True):
            return False
    if filters.created_after and metadata.created_at:
        created_at = parse_github_datetime(metadata.created_at, upper_bound=False)
        if created_at < parse_github_datetime(filters.created_after, upper_bound=False):
            return False
    if filters.created_before and metadata.created_at:
        created_at = parse_github_datetime(metadata.created_at, upper_bound=False)
        if created_at > parse_github_datetime(filters.created_before, upper_bound=True):
            return False
    if filters.language and metadata.language.casefold() != filters.language.casefold():
        return False
    metadata_topics = {topic.casefold() for topic in metadata.topics}
    return all(topic.casefold() in metadata_topics for topic in filters.topics)


def github_repository_excluded(
    repo: GitHubRepository,
    owner_type: Literal["User", "Organization"],
    filters: GitHubRepositoryFilters,
) -> bool:
    owner = repo.owner.casefold()
    source = repo.source.casefold()
    repo_name = repo.repo.casefold()
    if owner in filters.excluded_existing_owners:
        return True
    if owner_type == "Organization" and owner in {
        organization.casefold() for organization in filters.excluded_organizations
    }:
        return True
    if owner_type == "User" and owner in {user.casefold() for user in filters.excluded_users}:
        return True
    if source in {repository.casefold() for repository in filters.excluded_repositories}:
        return True
    return any(
        excluded_name.casefold() in repo_name for excluded_name in filters.excluded_repository_names
    )


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
    default_branch = default_branch_value.strip() if isinstance(default_branch_value, str) else ""
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


def github_repository_from_code_search_item(
    item: dict[str, object],
) -> tuple[GitHubImportRepository, str]:
    repository = item.get("repository")
    if not isinstance(repository, dict):
        raise GitHubSystemicError("GitHub code search result has no repository metadata")
    name_value = repository.get("name")
    full_name_value = repository.get("full_name")
    owner_value = repository.get("owner")
    if not isinstance(name_value, str) or not name_value.strip():
        raise GitHubSystemicError("GitHub code search result has no repository name")
    if not isinstance(full_name_value, str) or not isinstance(owner_value, dict):
        raise GitHubSystemicError("GitHub code search result has invalid ownership")
    owner_login_value = owner_value.get("login")
    owner_type = owner_value.get("type")
    if not isinstance(owner_login_value, str) or owner_type not in {"User", "Organization"}:
        raise GitHubSystemicError("GitHub code search result has invalid owner metadata")
    try:
        owner_login = validate_github_owner(owner_login_value)
    except SkillCliError as exc:
        raise GitHubSystemicError("GitHub code search result has an invalid owner login") from exc
    name = name_value.strip()
    expected_source = f"{owner_login}/{name}"
    if full_name_value.casefold() != expected_source.casefold():
        raise GitHubSystemicError("GitHub code search result has inconsistent ownership")
    default_branch_value = repository.get("default_branch")
    default_branch = default_branch_value.strip() if isinstance(default_branch_value, str) else ""
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
        normalized_token = token.strip()
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": user_agent,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if normalized_token:
            headers["Authorization"] = f"Bearer {normalized_token}"
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            headers=headers,
            follow_redirects=True,
            event_hooks={"request": [validate_github_request]},
        )
        self._verified_org_cache: OrderedDict[str, bool] = OrderedDict()
        self._etag_token_scope = (
            hashlib.sha256(normalized_token.encode("utf-8")).hexdigest() if normalized_token else ""
        )
        self._etag_cache_enabled = bool(normalized_token)
        self._etag_cache: dict[str, GitHubETagCacheEntry] = {}
        self._etag_cache_bytes = 0
        self._etag_cache_dirty: set[str] = set()
        self._rate_limit_budgets: dict[str, GitHubRateLimitBudget] = {}
        self._normalized_text_warnings: set[tuple[str, str, str, str]] = set()

    async def __aenter__(self) -> GitHubClient:
        if self._etag_cache_enabled:
            try:
                self._etag_cache = await load_github_etag_cache()
                self._etag_cache_bytes = sum(len(entry.body) for entry in self._etag_cache.values())
            except Exception:
                self._etag_cache_enabled = False
                logger.warning(
                    "github conditional response cache unavailable; continuing without it",
                    exc_info=True,
                )
        return self

    async def __aexit__(self, *args: object) -> None:
        try:
            if self._etag_cache_enabled and self._etag_cache_dirty:
                entries = [
                    self._etag_cache[cache_key]
                    for cache_key in self._etag_cache_dirty
                    if cache_key in self._etag_cache
                ]
                try:
                    await persist_github_etag_cache(entries)
                except Exception:
                    logger.warning(
                        "github conditional response cache could not be saved",
                        exc_info=True,
                    )
        finally:
            await self._client.aclose()

    async def _wait_for_known_rate_limit(self, resource: str | None, url: str) -> None:
        if resource is None:
            return
        budget = self._rate_limit_budgets.get(resource)
        if budget is None or budget.remaining > 0:
            return
        now_epoch_seconds = time.time()
        if budget.reset_epoch_seconds <= now_epoch_seconds:
            self._rate_limit_budgets.pop(resource, None)
            return
        wait_seconds = (
            budget.reset_epoch_seconds - now_epoch_seconds + GITHUB_RATE_LIMIT_WAIT_BUFFER_SECONDS
        )
        logger.warning(
            "github rate limit exhausted; waiting before request",
            extra={
                "request_host": urlparse(url).hostname,
                "request_path": urlparse(url).path,
                "rate_limit_reason": "primary",
                "rate_limit_resource": resource,
                "rate_limit_remaining": budget.remaining,
                "rate_limit_reset": budget.reset_epoch_seconds,
                "retry_wait_seconds": wait_seconds,
            },
        )
        await asyncio.sleep(wait_seconds)
        self._rate_limit_budgets.pop(resource, None)

    def _record_rate_limit_budget(
        self,
        response: object,
        fallback_resource: str | None,
    ) -> None:
        parsed = github_rate_limit_budget(response, fallback_resource=fallback_resource)
        if parsed is not None:
            resource, budget = parsed
            self._rate_limit_budgets[resource] = budget

    def _cache_key(self, url: str, params: dict[str, str] | None) -> str | None:
        if not self._etag_cache_enabled:
            return None
        return github_etag_cache_key(
            token_scope=self._etag_token_scope,
            url=url,
            params=params,
        )

    def _store_cache_response(self, cache_key: str | None, response: httpx.Response) -> None:
        if cache_key is None or response.status_code != 200:
            return
        headers = github_cacheable_response_headers(response)
        etag = headers.get("etag")
        if not etag or len(response.content) > GITHUB_ETAG_CACHE_MAX_ENTRY_BYTES:
            return
        previous = self._etag_cache.get(cache_key)
        if previous is not None:
            self._etag_cache_bytes -= len(previous.body)
        self._etag_cache[cache_key] = GitHubETagCacheEntry(
            cache_key=cache_key,
            etag=etag,
            response_headers=headers,
            body=response.content,
            last_accessed_at=datetime.now(UTC),
        )
        self._etag_cache_bytes += len(response.content)
        self._etag_cache_dirty.add(cache_key)
        while (
            len(self._etag_cache) > GITHUB_ETAG_CACHE_MAX_ENTRIES
            or self._etag_cache_bytes > GITHUB_ETAG_CACHE_MAX_BYTES
        ):
            expired_key, expired_entry = min(
                self._etag_cache.items(),
                key=lambda item: item[1].last_accessed_at,
            )
            self._etag_cache.pop(expired_key)
            self._etag_cache_bytes -= len(expired_entry.body)
            self._etag_cache_dirty.discard(expired_key)

    def _cached_response(
        self,
        entry: GitHubETagCacheEntry,
        not_modified_response: httpx.Response,
    ) -> httpx.Response:
        headers = dict(entry.response_headers)
        for name in GITHUB_NOT_MODIFIED_RESPONSE_HEADERS:
            value = github_response_header(not_modified_response, name)
            if value:
                headers[name] = value
        refreshed_entry = replace(
            entry,
            etag=headers.get("etag", entry.etag),
            response_headers={
                name: value
                for name, value in headers.items()
                if name in {"content-type", "etag", "last-modified"}
            },
            last_accessed_at=datetime.now(UTC),
        )
        self._etag_cache[entry.cache_key] = refreshed_entry
        self._etag_cache_dirty.add(entry.cache_key)
        return httpx.Response(
            status_code=200,
            headers=headers,
            content=entry.body,
            request=not_modified_response.request,
        )

    async def _get(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        follow_redirects: bool | None = None,
    ) -> httpx.Response:
        rate_limit_retry_attempt = 0
        transient_retry_attempt = 0
        resource = github_rate_limit_resource_for_request(url)
        cache_key = self._cache_key(url, params)
        use_conditional_request = cache_key in self._etag_cache if cache_key else False
        retried_unconditional_not_modified = False
        while True:
            await self._wait_for_known_rate_limit(resource, url)
            request_kwargs: dict[str, object] = {}
            if params is not None:
                request_kwargs["params"] = params
            if follow_redirects is not None:
                request_kwargs["follow_redirects"] = follow_redirects
            if use_conditional_request and cache_key is not None:
                request_kwargs["headers"] = {
                    "If-None-Match": self._etag_cache[cache_key].etag,
                }
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
            self._record_rate_limit_budget(response, resource)
            if response.status_code == 304:
                if cache_key is not None and cache_key in self._etag_cache:
                    return self._cached_response(self._etag_cache[cache_key], response)
                if retried_unconditional_not_modified:
                    return response
                use_conditional_request = False
                retried_unconditional_not_modified = True
                continue
            wait = github_rate_limit_wait(
                response,
                retry_attempt=rate_limit_retry_attempt,
                now_epoch_seconds=time.time(),
            )
            if wait is not None:
                if rate_limit_retry_attempt >= GITHUB_RATE_LIMIT_MAX_RETRIES:
                    logger.error(
                        "github request rate limit retries exhausted",
                        extra={
                            "response_status_code": response.status_code,
                            "github_request_id": github_response_header(
                                response, "x-github-request-id"
                            ),
                            "request_host": urlparse(url).hostname,
                            "request_path": urlparse(url).path,
                            "rate_limit_reason": wait.reason,
                            "rate_limit_resource": github_response_header(
                                response, "x-ratelimit-resource"
                            )
                            or resource,
                            "rate_limit_remaining": github_response_header(
                                response, "x-ratelimit-remaining"
                            ),
                            "rate_limit_reset": github_response_header(
                                response, "x-ratelimit-reset"
                            ),
                            "retry_attempt": rate_limit_retry_attempt,
                        },
                    )
                    return response
                rate_limit_retry_attempt += 1
                logger.warning(
                    "github request rate limited; waiting before retry",
                    extra={
                        "response_status_code": response.status_code,
                        "github_request_id": github_response_header(
                            response, "x-github-request-id"
                        ),
                        "request_host": urlparse(url).hostname,
                        "request_path": urlparse(url).path,
                        "rate_limit_reason": wait.reason,
                        "rate_limit_resource": github_response_header(
                            response, "x-ratelimit-resource"
                        ),
                        "rate_limit_remaining": github_response_header(
                            response, "x-ratelimit-remaining"
                        ),
                        "rate_limit_reset": github_response_header(response, "x-ratelimit-reset"),
                        "retry_attempt": rate_limit_retry_attempt,
                        "retry_wait_seconds": wait.seconds,
                    },
                )
                await asyncio.sleep(wait.seconds)
                if resource is not None:
                    self._rate_limit_budgets.pop(resource, None)
                continue
            if response.status_code < 500:
                self._store_cache_response(cache_key, response)
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
                    "github_request_id": github_response_header(response, "x-github-request-id"),
                    "retry_attempt": transient_retry_attempt,
                    "retry_wait_seconds": retry_wait,
                },
            )
            await asyncio.sleep(retry_wait)

    async def owner(self, owner: str) -> GitHubOwner:
        response = await self._get(f"{GITHUB_API_ROOT}/users/{quote(owner, safe='')}")
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
        response = await self._get(f"{GITHUB_API_ROOT}/orgs/{quote(owner, safe='')}")
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

    async def search_code_page(
        self,
        query: str,
        *,
        page: int,
    ) -> GitHubCodeSearchPage:
        response = await self._get(
            f"{GITHUB_API_ROOT}/search/code",
            params={
                "q": query,
                "sort": "indexed",
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
                    "GitHub code search failed",
                ),
            )
        payload = github_json(response, "code search")
        if not isinstance(payload, dict):
            raise GitHubSystemicError("GitHub returned an invalid code search response")
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
            raise GitHubSystemicError("GitHub returned an invalid code search response")
        if incomplete_results:
            raise GitHubSystemicError("GitHub code search returned incomplete results")
        return GitHubCodeSearchPage(
            total_count=total_count,
            incomplete_results=incomplete_results,
            items=items,
        )

    async def _iter_code_search_repositories(
        self,
        filters: GitHubRepositoryFilters,
        target: GitHubSearchTarget,
        *,
        recursive: bool,
        subfolder: str,
        stats: GitHubDiscoveryStats,
        budget: GitHubSearchBudget,
    ) -> AsyncIterator[GitHubImportRepository]:
        if budget.exhausted:
            return
        query = github_skill_code_search_query(
            target,
            recursive=recursive,
            subfolder=subfolder,
        )
        first_page = await self.search_code_page(query, page=1)
        stats.search_query_count += 1
        remaining_budget = budget.remaining
        if first_page.total_count > GITHUB_SEARCH_RESULT_LIMIT and (
            remaining_budget is None or remaining_budget > GITHUB_SEARCH_RESULT_LIMIT
        ):
            raise SkillCliError(
                "GitHub code search found more than 1,000 SKILL.md matches; add a narrower "
                "target, subfolder, repository filter, or --max-repositories"
            )
        maximum_results = min(first_page.total_count, GITHUB_SEARCH_RESULT_LIMIT)
        page_count = (maximum_results + GITHUB_REPOSITORIES_PER_PAGE - 1) // (
            GITHUB_REPOSITORIES_PER_PAGE
        )
        seen_sources: set[str] = set()
        for page_number in range(1, page_count + 1):
            if budget.exhausted:
                return
            page = (
                first_page
                if page_number == 1
                else await self.search_code_page(query, page=page_number)
            )
            if page_number > 1:
                stats.search_query_count += 1
            stats.listed_repository_count += len(page.items)
            for raw_item in page.items:
                candidate, owner_type = github_repository_from_code_search_item(raw_item)
                source_key = candidate.repo.source.casefold()
                if source_key in seen_sources:
                    stats.filtered_repository_count += 1
                    continue
                seen_sources.add(source_key)
                if github_repository_excluded(candidate.repo, owner_type, filters):
                    stats.filtered_repository_count += 1
                    continue
                metadata = await self.repository_metadata(candidate.repo)
                if filters.verified_orgs_only:
                    if owner_type != "Organization" or not await self.organization_is_verified(
                        candidate.repo.owner
                    ):
                        stats.filtered_repository_count += 1
                        continue
                if not github_metadata_matches_filters(metadata, filters):
                    stats.filtered_repository_count += 1
                    continue
                if not budget.consume():
                    return
                stats.active_repository_count += 1
                yield GitHubImportRepository(
                    repo=candidate.repo,
                    default_branch=metadata.default_branch,
                    owner_avatar_url=metadata.owner_avatar_url or candidate.owner_avatar_url,
                )

    async def repository_has_skill_code(
        self,
        repo: GitHubRepository,
        *,
        recursive: bool,
        subfolder: str,
    ) -> bool:
        query = github_skill_repository_code_search_query(
            repo,
            recursive=recursive,
            subfolder=subfolder,
        )
        page = await self.search_code_page(query, page=1)
        return bool(page.items)

    async def _iter_repository_search_skill_repositories(
        self,
        filters: GitHubRepositoryFilters,
        target: GitHubSearchTarget,
        *,
        created_start: datetime,
        created_end: datetime,
        recursive: bool,
        subfolder: str,
        stats: GitHubDiscoveryStats,
        budget: GitHubSearchBudget,
    ) -> AsyncIterator[GitHubImportRepository]:
        async for repository in self._search_repository_window(
            filters,
            target,
            created_start=created_start,
            created_end=created_end,
            stats=stats,
            budget=GitHubSearchBudget(remaining=None),
            count_active=False,
        ):
            if budget.exhausted:
                return
            if not await self.repository_has_skill_code(
                repository.repo,
                recursive=recursive,
                subfolder=subfolder,
            ):
                stats.filtered_repository_count += 1
                continue
            if not budget.consume():
                return
            stats.active_repository_count += 1
            yield repository

    async def _search_repository_window(
        self,
        filters: GitHubRepositoryFilters,
        target: GitHubSearchTarget,
        *,
        created_start: datetime,
        created_end: datetime,
        stats: GitHubDiscoveryStats,
        budget: GitHubSearchBudget,
        count_active: bool = True,
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
        must_split = first_page.total_count > GITHUB_SEARCH_RESULT_LIMIT and (
            remaining_budget is None or remaining_budget > GITHUB_SEARCH_RESULT_LIMIT
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
                count_active=count_active,
            ):
                yield repository
            async for repository in self._search_repository_window(
                filters,
                target,
                created_start=right_start,
                created_end=created_end,
                stats=stats,
                budget=budget,
                count_active=count_active,
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
                if github_repository_excluded(candidate.repo, owner_type, filters):
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
                if count_active:
                    stats.active_repository_count += 1
                yield candidate

    async def iter_repositories(
        self,
        filters: GitHubRepositoryFilters,
        stats: GitHubDiscoveryStats,
        *,
        recursive: bool = False,
        subfolder: str = "",
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
            GitHubSearchTarget(qualifier="org", value=owner) for owner in filters.organizations
        )
        targets.extend(GitHubSearchTarget(qualifier="user", value=owner) for owner in filters.users)
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
            if recursive:
                if filters.topics or filters.repository_names:
                    async for repository in self._iter_repository_search_skill_repositories(
                        filters,
                        target,
                        created_start=start,
                        created_end=end,
                        recursive=recursive,
                        subfolder=subfolder,
                        stats=stats,
                        budget=budget,
                    ):
                        yield repository
                    continue
                async for repository in self._iter_code_search_repositories(
                    filters,
                    target,
                    recursive=recursive,
                    subfolder=subfolder,
                    stats=stats,
                    budget=budget,
                ):
                    yield repository
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
                    default_branch_value.strip() if isinstance(default_branch_value, str) else ""
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
        response = await self._get(f"https://api.github.com/repos/{repo.owner}/{repo.repo}")
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
            raise SkillCliError(f"GitHub repository visibility is unavailable: {repo.source}")
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
        if not isinstance(full_name, str) or full_name.casefold() != repo.source.casefold():
            raise SkillCliError(f"GitHub repository moved to another owner: {repo.source}")
        default_branch = payload.get("default_branch")
        if not isinstance(default_branch, str) or not default_branch.strip():
            raise SkillCliError(f"GitHub repository has no default branch: {repo.source}")
        owner = payload.get("owner")
        owner_avatar_url = ""
        if isinstance(owner, dict) and isinstance(owner.get("avatar_url"), str):
            owner_avatar_url = owner["avatar_url"].strip()
        created_at = payload.get("created_at")
        pushed_at = payload.get("pushed_at")
        language = payload.get("language")
        stargazers_count = payload.get("stargazers_count")
        topics = payload.get("topics")
        return GitHubRepositoryMetadata(
            default_branch=default_branch.strip(),
            owner_avatar_url=owner_avatar_url,
            fork=fork,
            archived=archived,
            created_at=created_at.strip() if isinstance(created_at, str) else "",
            disabled=disabled,
            language=language.strip() if isinstance(language, str) else "",
            pushed_at=pushed_at.strip() if isinstance(pushed_at, str) else "",
            stargazers_count=stargazers_count
            if isinstance(stargazers_count, int) and not isinstance(stargazers_count, bool)
            else 0,
            topics=tuple(topic for topic in topics if isinstance(topic, str))
            if isinstance(topics, list)
            else (),
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
            raise GitHubTreeTruncatedError("GitHub tree is truncated; repository scan skipped")
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
                f"GitHub file contains a NUL byte at offset {nul_offset} (line {line_number})",
            )
        try:
            decoded = content.decode("utf-8", errors=GITHUB_TEXT_DECODE_ERRORS)
        except UnicodeDecodeError as exc:
            raise InvalidSkillTextError(path, "GitHub file is not UTF-8 text") from exc
        normalized_byte_count = decoded.count(WINDOWS_1252_EM_DASH_SENTINEL)
        if normalized_byte_count:
            decoded = decoded.replace(WINDOWS_1252_EM_DASH_SENTINEL, "\N{EM DASH}")
            warning_key = (repo.source, ref, path, "windows-1252-em-dash")
            if warning_key not in self._normalized_text_warnings:
                self._normalized_text_warnings.add(warning_key)
                logger.warning(
                    "github file normalized Windows-1252 em dash bytes",
                    extra={
                        "source": repo.source,
                        "source_path": path,
                        "normalized_byte_count": normalized_byte_count,
                    },
                )
        decoded, normalized_control_count = normalize_github_text_mojibake(decoded)
        if normalized_control_count:
            warning_key = (repo.source, ref, path, "mojibake")
            if warning_key not in self._normalized_text_warnings:
                self._normalized_text_warnings.add(warning_key)
                logger.warning(
                    "github file normalized mojibake",
                    extra={
                        "source": repo.source,
                        "source_path": path,
                        "normalized_control_count": normalized_control_count,
                    },
                )
        control = unsupported_text_control(decoded)
        if control is not None:
            offset, character = control
            raise InvalidSkillTextError(
                path,
                "GitHub file contains unsupported control character "
                f"U+{ord(character):04X} at character offset {offset}",
            )
        return decoded


def should_skip_tree_path(path: str) -> bool:
    return any(part in SKIPPED_PATH_PARTS for part in PurePosixPath(path).parts)


def is_regular_skill_root(item: GitHubTreeItem) -> bool:
    return (
        item.type == "blob"
        and item.mode != "120000"
        and PurePosixPath(item.path).name == "SKILL.md"
        and not should_skip_tree_path(item.path)
    )


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
        or len(path) > MAX_SKILL_PATH_CHARS
        or path.startswith("/")
        or "\\" in path
        or any(
            ord(character) < 32
            or 127 <= ord(character) <= 159
            or ord(character) == 0x061C
            or 0x200E <= ord(character) <= 0x200F
            or 0x202A <= ord(character) <= 0x202E
            or 0x2066 <= ord(character) <= 0x2069
            for character in path
        )
    ):
        raise ValueError("skill file path must be a safe relative POSIX path")

    normalized = PurePosixPath(path).as_posix()
    parts = path.split("/")
    if (
        normalized != path
        or len(parts) > MAX_SKILL_PATH_PARTS
        or any(
            part in {"", ".", ".."}
            or ":" in part
            or part.endswith((".", " "))
            or len(part.encode("utf-8")) > 255
            or WINDOWS_RESERVED_PATH_PATTERN.match(part)
            for part in parts
        )
    ):
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
        skill_root_from_skill_path(item.path) for item in tree if is_regular_skill_root(item)
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


def markdown_instruction_lines(contents: str) -> list[str]:
    lines: list[str] = []
    fence: str | None = None
    for line in contents.splitlines():
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(line)
    return lines


def normalize_dependency_target(target: str) -> str:
    stripped = target.strip().strip("<>")
    if not stripped:
        return ""
    without_fragment = stripped.split("#", 1)[0]
    if not any(character in without_fragment for character in "*["):
        without_fragment = without_fragment.split("?", 1)[0]
    return without_fragment.strip()


def looks_like_local_dependency(
    target: str,
    *,
    allow_extensionless: bool = False,
    allow_bare_directory: bool = False,
) -> bool:
    normalized = normalize_dependency_target(target)
    if not normalized or normalized.startswith(("/", "#", "~/", "@")) or "\\" in normalized:
        return False
    if normalized.casefold() in NON_PATH_REFERENCE_LITERALS:
        return False
    lowered = normalized.lower()
    if lowered.startswith(("http://", "https://", "mailto:", "data:", "//")):
        return False
    if any(marker in normalized for marker in ("${", "{{", "}}", "<", ">")):
        return False
    if allow_extensionless:
        return not any(character.isspace() for character in normalized) and ":" not in normalized
    if allow_bare_directory and normalized.endswith("/"):
        return not any(character.isspace() for character in normalized) and ":" not in normalized
    # Unquoted prose commonly contains slash-delimited concepts such as A/B,
    # build/don't-build, or assumption/open-question. Treat only path-shaped
    # directive values as dependencies; Markdown links remain intentionally
    # more permissive above.
    if normalized.endswith("/") and not normalized.startswith(("./", "../")):
        return False
    return bool(LOCAL_PATH_CANDIDATE_PATTERN.fullmatch(normalized))


def local_dependency_references(contents: str) -> list[LocalDependencyReference]:
    references: dict[tuple[str, str], LocalDependencyReference] = {}

    def add(
        target: str,
        *,
        required: bool,
        kind: str,
        allow_bare_directory: bool = False,
    ) -> None:
        normalized = normalize_dependency_target(target)
        if not looks_like_local_dependency(
            normalized,
            allow_extensionless=kind in {"link", "asset"},
            allow_bare_directory=allow_bare_directory,
        ):
            return
        key = (normalized, kind)
        previous = references.get(key)
        references[key] = LocalDependencyReference(
            target=normalized,
            required=required or (previous.required if previous else False),
            kind=kind,
        )

    # markdown-it supplies parsed destinations rather than link labels and excludes
    # fenced code. This avoids treating labels such as "SKILL.md" as dependencies.
    source_lines = contents.splitlines()
    for token in MARKDOWN.parse(contents):
        start, end = token.map or (0, 0)
        block = "\n".join(source_lines[start:end])
        required_link = not bool(
            OPTIONAL_REFERENCE_PATTERN.search(block) or RUNTIME_OUTPUT_PATTERN.search(block)
        )
        for child in token.children or []:
            if child.type == "link_open":
                href = child.attrGet("href")
                if href:
                    add(href, required=required_link, kind="link")
            elif child.type == "image":
                source = child.attrGet("src")
                if source:
                    add(source, required=False, kind="asset")

    for line in markdown_instruction_lines(contents):
        directives = list(REFERENCE_DIRECTIVE_PATTERN.finditer(line))
        runtime_output = RUNTIME_OUTPUT_PATTERN.search(line)
        required = not bool(OPTIONAL_REFERENCE_PATTERN.search(line)) and not runtime_output
        if not directives or runtime_output:
            continue
        for match in INLINE_CODE_PATTERN.finditer(line):
            directive = next(
                (
                    candidate
                    for candidate in reversed(directives)
                    if candidate.end() <= match.start()
                ),
                None,
            )
            if directive is None:
                continue
            gap = line[directive.end() : match.start()]
            # Bind a path to the directive immediately introducing it. A broad
            # line-level match turns versions, domains, field names, and examples
            # into dependencies whenever prose happens to contain words such as
            # "use", "include", or "review" elsewhere on the same line.
            if len(gap) > 64 or len(re.findall(r"\b\w+\b", gap)) > 6:
                continue
            target = normalize_dependency_target(match.group(1))
            # Inline code is also used for API names, model artifacts, versions,
            # and other runtime values. Require a directory component (including
            # an explicit ./ or ../) before treating it as a package dependency.
            # Markdown links remain the supported way to reference a file beside
            # SKILL.md without a directory component.
            if "/" not in target:
                continue
            add(
                target,
                required=required,
                kind="directive",
                allow_bare_directory=True,
            )
        line_without_links = MARKDOWN_LINK_PATTERN.sub(" ", INLINE_CODE_PATTERN.sub(" ", line))
        for match in PLAIN_LOCAL_PATH_PATTERN.finditer(line_without_links):
            target = match.group(0)
            if not target.startswith(("./", "../")):
                continue
            directive = next(
                (
                    candidate
                    for candidate in reversed(directives)
                    if candidate.end() <= match.start()
                ),
                None,
            )
            if directive is None or match.start() - directive.end() > 64:
                continue
            add(target, required=required, kind="directive")
    return sorted(references.values(), key=lambda item: (item.target, item.kind))


def resolve_repository_dependency(source_path: str, target: str) -> str | None:
    decoded = unquote(normalize_dependency_target(target))
    if not decoded:
        return ""
    parts = list(PurePosixPath(source_path).parent.parts)
    for part in decoded.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    resolved = "/".join(parts)
    try:
        return validate_skill_file_path(resolved.rstrip("/"))
    except ValueError:
        return None


def bundle_dependency_matches(
    items: list[GitHubTreeItem],
    *,
    skill_root: str,
    source_path: str,
    reference: LocalDependencyReference,
) -> tuple[str, list[GitHubTreeItem]]:
    resolved = resolve_repository_dependency(source_path, reference.target)
    if not resolved:
        return "invalid", []
    if not path_is_within_skill_root(resolved, skill_root):
        return "external", []
    regular_blobs = [
        item
        for item in items
        if item.type == "blob" and item.mode != "120000" and not should_skip_tree_path(item.path)
    ]
    if any(character in resolved for character in "*?["):
        matches = sorted(
            (item for item in regular_blobs if fnmatch.fnmatchcase(item.path, resolved)),
            key=lambda item: item.path,
        )
        return ("glob", matches) if matches else ("missing", [])
    exact = next((item for item in regular_blobs if item.path == resolved), None)
    if exact is not None:
        return "file", [exact]
    prefix = f"{resolved.rstrip('/')}/"
    directory = sorted(
        (item for item in regular_blobs if item.path.startswith(prefix)),
        key=lambda item: item.path,
    )
    if directory:
        return "directory", directory
    return "missing", []


def valid_source_skill_document(contents: str) -> bool:
    metadata = parse_frontmatter(contents)
    if not metadata.get("name") or not metadata.get("description"):
        return False
    lines = contents.splitlines()
    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration:
        return False
    return any(line.strip() for line in lines[closing_index + 1 :])


async def fetch_skill_bundle(
    *,
    client: GitHubClient,
    repo: GitHubRepository,
    ref: str,
    tree: list[GitHubTreeItem],
    skill_path: str,
    items: list[GitHubTreeItem] | None = None,
) -> FetchedSkillBundle:
    if items is None:
        items = skill_bundle_tree_items(tree, skill_path=skill_path)
    root = skill_root_from_skill_path(skill_path)
    for item in items:
        try:
            validate_skill_file_path(relative_skill_file_path(root, item.path))
        except ValueError as exc:
            raise InvalidSkillBundleError(item.path, str(exc)) from exc
    source_skill_md, source_skill_contents = await fetch_skill_md(
        client=client,
        repo=repo,
        ref=ref,
        skill_path=skill_path,
    )
    semaphore = asyncio.Semaphore(MAX_BUNDLE_FETCH_CONCURRENCY)
    fetched_bytes: dict[str, bytes] = {skill_path: source_skill_contents}
    resolution_issues: list[SkillResolutionIssue] = []
    dependency_manifest: list[SkillDependencyManifestEntry] = []
    if not valid_source_skill_document(source_skill_md):
        resolution_issues.append(
            {
                "sourcePath": "SKILL.md",
                "target": "SKILL.md",
                "reason": (
                    "source SKILL.md must have nonempty name and description frontmatter "
                    "plus instructions"
                ),
                "required": True,
            }
        )

    async def fetch_item(item: GitHubTreeItem) -> tuple[str, bytes]:
        async with semaphore:
            contents = await client.raw_file_bytes(repo, ref, item.path)
        if len(contents) > MAX_SKILL_FILE_BYTES:
            raise InvalidSkillBundleError(
                item.path,
                f"skill file exceeds {MAX_SKILL_FILE_BYTES} bytes",
            )
        return item.path, contents

    initial_fetched = await asyncio.gather(
        *(fetch_item(item) for item in items if item.path != skill_path)
    )
    fetched_bytes.update(initial_fetched)

    pending_instruction_paths = [skill_path]
    validated_instruction_paths: set[str] = set()
    while pending_instruction_paths:
        source_path = pending_instruction_paths.pop(0)
        if source_path in validated_instruction_paths:
            continue
        validated_instruction_paths.add(source_path)
        try:
            contents = fetched_bytes[source_path].decode("utf-8")
        except (KeyError, UnicodeDecodeError):
            continue
        for reference in local_dependency_references(contents):
            kind, matches = bundle_dependency_matches(
                items,
                skill_root=root,
                source_path=source_path,
                reference=reference,
            )
            source_relative = relative_skill_file_path(root, source_path)
            resolved_paths = [relative_skill_file_path(root, item.path) for item in matches]
            if len(dependency_manifest) < MAX_SKILL_DEPENDENCY_MANIFEST_ENTRIES:
                dependency_manifest.append(
                    {
                        "sourcePath": source_relative,
                        "target": reference.target,
                        "kind": kind,
                        "required": reference.required,
                        "resolvedPaths": resolved_paths,
                    }
                )
            if not matches:
                if len(resolution_issues) < MAX_SKILL_RESOLUTION_ISSUES:
                    if kind == "external":
                        reason = "reference leaves the skill directory"
                    elif kind == "invalid":
                        reason = "reference is unsafe"
                    else:
                        reason = "skill bundle reference did not resolve"
                    resolution_issues.append(
                        {
                            "sourcePath": source_relative,
                            "target": reference.target,
                            "reason": reason,
                            "required": reference.required,
                        }
                    )
                continue
            if reference.required:
                pending_instruction_paths.extend(
                    item.path
                    for item in matches
                    if item.path.lower().endswith((".md", ".mdx"))
                    and item.path not in validated_instruction_paths
                    and item.path not in pending_instruction_paths
                )

    files: list[SkillSnapshotFile] = []
    for path, item in sorted(
        ((item.path, item) for item in items),
        key=lambda pair: (relative_skill_file_path(root, pair[0]) != "SKILL.md", pair[0]),
    ):
        files.append(
            snapshot_file_from_bytes(
                path=relative_skill_file_path(root, path),
                contents=fetched_bytes[path],
                executable=item.mode == "100755",
            )
        )
    bundle_size = sum(len(contents) for contents in fetched_bytes.values())
    if bundle_size > MAX_SKILL_BUNDLE_BYTES:
        raise InvalidSkillBundleError(
            skill_path,
            f"skill bundle exceeds {MAX_SKILL_BUNDLE_BYTES} bytes",
        )
    resolution_status: SkillResolutionStatus = (
        "incomplete" if any(issue["required"] for issue in resolution_issues) else "complete"
    )
    return FetchedSkillBundle(
        source_skill_md=source_skill_md,
        skill_md=source_skill_md,
        files=files,
        bundle_size=bundle_size,
        bundle_format_version=SKILL_BUNDLE_FORMAT_VERSION,
        source_commit_sha=ref,
        source_entrypoint="SKILL.md",
        resolution_status=resolution_status,
        resolution_issues=resolution_issues,
        dependency_manifest=dependency_manifest,
    )


async def fetch_skill_md(
    *,
    client: GitHubClient,
    repo: GitHubRepository,
    ref: str,
    skill_path: str,
) -> tuple[str, bytes]:
    skill_md = await client.raw_file(repo, ref, skill_path)
    if not skill_md.strip():
        raise InvalidSkillTextError(skill_path, "GitHub SKILL.md is empty")

    skill_contents = skill_md.encode("utf-8")
    if len(skill_contents) > MAX_SKILL_FILE_BYTES:
        raise InvalidSkillBundleError(
            skill_path,
            f"skill file exceeds {MAX_SKILL_FILE_BYTES} bytes",
        )
    return skill_md, skill_contents


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


async def lock_skill_refresh_state(
    session: AsyncSession,
    target: SkillRefreshTarget,
) -> tuple[Skill, SkillSnapshot]:
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
    return skill, current_snapshot


async def refresh_existing_skill_snapshot(
    session: AsyncSession,
    target: SkillRefreshTarget,
    *,
    bundle: FetchedSkillBundle,
) -> tuple[str, bool]:
    if bundle.resolution_status != "complete":
        raise SkillCliError(f"refusing to store incomplete skill package: {target.id}")
    skill, current_snapshot = await lock_skill_refresh_state(session, target)

    hash_value = content_hash(bundle.files)
    metadata_unchanged = (
        current_snapshot.bundle_format_version == bundle.bundle_format_version
        and current_snapshot.source_commit_sha == bundle.source_commit_sha
        and current_snapshot.source_entrypoint == bundle.source_entrypoint
        and current_snapshot.resolution_status == bundle.resolution_status
        and current_snapshot.resolution_issues == bundle.resolution_issues
        and current_snapshot.dependency_manifest == bundle.dependency_manifest
    )
    if current_snapshot.content_hash == hash_value and metadata_unchanged:
        return hash_value, False
    snapshot = await upsert_skill_snapshot(
        session,
        skill,
        skill_md=bundle.skill_md,
        files=bundle.files,
        bundle_format_version=bundle.bundle_format_version,
        source_commit_sha=bundle.source_commit_sha,
        source_entrypoint=bundle.source_entrypoint,
        resolution_status=bundle.resolution_status,
        resolution_issues=bundle.resolution_issues,
        dependency_manifest=bundle.dependency_manifest,
    )
    return snapshot.content_hash or hash_value, True


async def save_refreshed_skill(
    target: SkillRefreshTarget,
    *,
    bundle: FetchedSkillBundle,
) -> tuple[str, bool]:
    async with AsyncSessionLocal() as session:
        try:
            result = await refresh_existing_skill_snapshot(
                session,
                target,
                bundle=bundle,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return result


async def remove_incomplete_refreshed_skill(target: SkillRefreshTarget) -> None:
    async with AsyncSessionLocal() as session:
        try:
            skill, _snapshot = await lock_skill_refresh_state(session, target)
            await session.execute(delete(Skill).where(Skill.id == skill.id))
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def discover_skill_paths(
    tree: list[GitHubTreeItem],
    *,
    recursive: bool,
    subfolder: str,
) -> list[str]:
    regular_skill_paths = {item.path for item in tree if is_regular_skill_root(item)}
    skill_path = f"{subfolder}/SKILL.md" if subfolder else "SKILL.md"
    if not recursive:
        if skill_path in regular_skill_paths:
            return [skill_path]
        if subfolder:
            raise SkillNotFoundError(f"No SKILL.md found in GitHub subfolder: {subfolder}")
        raise SkillNotFoundError("No SKILL.md found in GitHub repository root")

    if subfolder:
        prefix = f"{subfolder}/"
        skill_paths = [
            path
            for path in regular_skill_paths
            if path == skill_path or (path.startswith(prefix) and path.endswith("/SKILL.md"))
        ]
    else:
        skill_paths = [
            path for path in regular_skill_paths if path == "SKILL.md" or path.endswith("/SKILL.md")
        ]
    if skill_paths:
        return sorted(skill_paths)
    if subfolder:
        raise SkillNotFoundError(f"No SKILL.md found in GitHub subfolder: {subfolder}")
    raise SkillNotFoundError("No SKILL.md found in GitHub repository")


def skill_import_metadata(
    *,
    repo: GitHubRepository,
    skill_path: str,
    import_subfolder: str,
    skill_md: str,
) -> tuple[str, str, str, str]:
    root = skill_root_from_skill_path(skill_path)
    frontmatter = parse_frontmatter(skill_md)
    name = (frontmatter.get("name") or Path(root).name or repo.repo).strip()
    slug = validate_skill_slug(slug_from_skill_root(skill_slug_root(root, import_subfolder), name))
    description = (frontmatter.get("description") or "").strip()
    return root, name, slug, description


async def plan_skill_import(
    *,
    client: GitHubClient,
    repo: GitHubRepository,
    ref: str,
    tree: list[GitHubTreeItem],
    skill_path: str,
    import_subfolder: str,
    current_repository_bytes: int,
) -> tuple[PlannedSkillImport, int]:
    bundle_items = skill_bundle_tree_items(tree, skill_path=skill_path)
    repository_bytes = checked_github_import_size(
        current_repository_bytes,
        sum(item.size for item in bundle_items),
    )
    skill_md, _skill_contents = await fetch_skill_md(
        client=client,
        repo=repo,
        ref=ref,
        skill_path=skill_path,
    )
    _root, _name, slug, _description = skill_import_metadata(
        repo=repo,
        skill_path=skill_path,
        import_subfolder=import_subfolder,
        skill_md=skill_md,
    )
    return PlannedSkillImport(skill_path=skill_path, slug=slug), repository_bytes


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
    resolved_slug: str | None = None,
) -> ImportedSkill:
    root = skill_root_from_skill_path(skill_path)
    bundle = await fetch_skill_bundle(
        client=client,
        repo=repo,
        ref=fetch_ref,
        tree=tree,
        skill_path=skill_path,
        items=bundle_items,
    )
    _root, name, derived_slug, description = skill_import_metadata(
        repo=repo,
        skill_path=skill_path,
        import_subfolder=import_subfolder,
        skill_md=bundle.source_skill_md,
    )
    slug = validate_skill_slug(resolved_slug or derived_slug)
    repository_url = f"{repo.url}/tree/{fetch_ref}"
    if root:
        encoded_root = "/".join(quote(part, safe="") for part in root.split("/"))
        repository_url = f"{repository_url}/{encoded_root}"
    logger.info(
        "github skill import fetched skill file",
        extra={
            "source": repo.source,
            "skill_id": f"{repo.source}/{slug}",
            "ref": ref,
            "resolved_ref": fetch_ref,
            "source_path": skill_path,
            "skill_slug": slug,
            "skill_name": name,
            "skill_root": root,
            "skill_md_bytes": len(bundle.source_skill_md.encode("utf-8")),
            "skill_file_count": len(bundle.files),
            "skill_bundle_bytes": bundle.bundle_size,
            "skill_resolution_status": bundle.resolution_status,
            "skill_resolution_issue_count": len(bundle.resolution_issues),
        },
    )
    if bundle.resolution_status == "incomplete":
        required_issues = [
            f"{issue['sourcePath']} -> {issue['target']}: {issue['reason']}"
            for issue in bundle.resolution_issues
            if issue["required"]
        ]
        failure_reason = "; ".join(required_issues)[:GITHUB_ERROR_BODY_MAX_CHARS]
        logger.warning(
            "github skill import rejected incomplete skill",
            extra={
                "source": repo.source,
                "skill_id": f"{repo.source}/{slug}",
                "failure_reason": failure_reason,
            },
        )
        raise InvalidSkillBundleError(
            skill_path,
            f"skill package is not self-contained: {failure_reason}",
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
        skill_md=bundle.skill_md,
        files=bundle.files,
        source_type="github",
        install_url=repository_url,
        website_url=repository_url,
        repository_url=repo.url,
        repository_subfolder=root,
        repository_ref=ref,
        bundle_format_version=bundle.bundle_format_version,
        source_commit_sha=bundle.source_commit_sha,
        source_entrypoint=bundle.source_entrypoint,
        resolution_status=bundle.resolution_status,
        resolution_issues=bundle.resolution_issues,
        dependency_manifest=bundle.dependency_manifest,
    )
    return ImportedSkill(
        payload=payload,
        source_path=skill_path,
        bundle_size=bundle.bundle_size,
    )


def validate_unique_imported_skill_slugs(imported: list[ImportedSkill]) -> None:
    paths_by_slug: dict[str, str] = {}
    for item in imported:
        slug = item.payload.slug
        previous_path = paths_by_slug.get(slug)
        if previous_path is not None:
            raise SkillCliError(
                f"multiple skill paths resolve to slug {slug}: {previous_path}, {item.source_path}"
            )
        paths_by_slug[slug] = item.source_path


def validate_unique_planned_skill_slugs(planned: list[PlannedSkillImport]) -> None:
    paths_by_slug: dict[str, str] = {}
    for item in planned:
        previous_path = paths_by_slug.get(item.slug)
        if previous_path is not None:
            raise SkillCliError(
                f"multiple skill paths resolve to slug {item.slug}: "
                f"{previous_path}, {item.skill_path}"
            )
        paths_by_slug[item.slug] = item.skill_path


def repository_collision_slug(slug: str, skill_path: str) -> str:
    source_root = skill_root_from_skill_path(skill_path)
    suffix = hashlib.sha256(source_root.encode("utf-8")).hexdigest()
    maximum_prefix_length = MAX_SKILL_SLUG_LENGTH - len(suffix) - 1
    prefix = slug[:maximum_prefix_length].rstrip("-_") or "skill"
    return validate_skill_slug(f"{prefix}-{suffix}")


def disambiguate_planned_skill_slugs(
    planned: list[PlannedSkillImport],
) -> tuple[list[PlannedSkillImport], dict[str, list[str]]]:
    paths_by_slug: dict[str, list[str]] = {}
    for item in planned:
        paths_by_slug.setdefault(item.slug, []).append(item.skill_path)

    collisions = {slug: paths for slug, paths in paths_by_slug.items() if len(paths) > 1}
    if not collisions:
        return planned, {}

    resolved = [
        replace(
            item,
            slug=repository_collision_slug(item.slug, item.skill_path),
        )
        if item.slug in collisions
        else item
        for item in planned
    ]
    validate_unique_planned_skill_slugs(resolved)
    return resolved, collisions


async def call_optional_session_method(session: object, name: str) -> None:
    method = getattr(session, name, None)
    if not callable(method):
        return
    result = method()
    if asyncio.iscoroutine(result):
        await result


def is_transient_database_disconnect(exc: BaseException) -> bool:
    if not isinstance(exc, DBAPIError):
        return False
    if exc.connection_invalidated:
        return True
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "connection is closed",
            "connection was closed",
            "connection reset",
            "connection terminated",
            "server closed the connection",
            "underlying connection is closed",
        )
    )


async def rollback_import_session(session: object) -> None:
    try:
        await call_optional_session_method(session, "rollback")
    except DBAPIError:
        # The failed connection is discarded with the session. Preserve the
        # original database exception so retry classification remains accurate.
        pass


async def save_imported_skill(imported_skill: ImportedSkill) -> SavedImportedSkill:
    for attempt in range(GITHUB_DATABASE_MAX_RETRIES + 1):
        retry_wait: float | None = None
        retry_reason = ""
        async with AsyncSessionLocal() as session:
            try:
                skill, snapshot = await add_skill(
                    session,
                    imported_skill.payload,
                    preserve_catalog_state=True,
                )
                await call_optional_session_method(session, "flush")
                await session.commit()
                return SavedImportedSkill(
                    source=skill.source,
                    slug=skill.slug,
                    source_path=imported_skill.source_path,
                    content_hash=snapshot.content_hash,
                )
            except SkillCliError:
                await rollback_import_session(session)
                raise
            except Exception as exc:
                await rollback_import_session(session)
                if (
                    attempt >= GITHUB_DATABASE_MAX_RETRIES
                    or not is_transient_database_disconnect(exc)
                ):
                    raise
                retry_wait = min(
                    GITHUB_DATABASE_RETRY_BASE_SECONDS * (2**attempt),
                    GITHUB_DATABASE_RETRY_MAX_SECONDS,
                )
                retry_reason = str(exc) or type(exc).__name__

        logger.warning(
            "github skill import database connection lost; retrying skill",
            extra={
                "source": imported_skill.payload.source,
                "skill_id": (
                    f"{imported_skill.payload.source}/{imported_skill.payload.slug}"
                ),
                "source_path": imported_skill.source_path,
                "retry_attempt": attempt + 1,
                "retry_wait_seconds": retry_wait,
                "failure_reason": retry_reason,
            },
        )
        await asyncio.sleep(retry_wait)

    raise RuntimeError("unreachable GitHub database retry state")


async def save_imported_repository(
    imported: list[ImportedSkill],
) -> list[SavedImportedSkill]:
    return [await save_imported_skill(item) for item in imported]


async def load_existing_github_skill_owners() -> frozenset[str]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(func.lower(Skill.source_owner))
            .where(
                Skill.source_type == "github",
                Skill.source_owner != "",
            )
            .distinct()
        )
        owners = [validate_github_owner(owner) for owner in result.scalars().all()]
    return frozenset(owner.casefold() for owner in owners)


async def import_github_from_args(args: argparse.Namespace) -> int:
    configure_github_import_output(str(getattr(args, "output", "json") or "json"))
    filters = github_repository_filters_from_args(args)
    exclude_existing_owners = bool(getattr(args, "exclude_existing_owners", False))
    if exclude_existing_owners:
        filters = replace(
            filters,
            excluded_existing_owners=await load_existing_github_skill_owners(),
        )
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
        "recursive": bool(getattr(args, "recursive", False)),
        "repository_filters": {
            "min_stars": filters.min_stars,
            "max_stars": filters.max_stars,
            "pushed_after": filters.pushed_after,
            "pushed_before": filters.pushed_before,
            "created_after": filters.created_after,
            "created_before": filters.created_before,
            "language": filters.language,
            "repository_names": filters.repository_names,
            "excluded_organizations": filters.excluded_organizations,
            "excluded_users": filters.excluded_users,
            "exclude_existing_owners": exclude_existing_owners,
            "excluded_existing_owner_count": len(filters.excluded_existing_owners),
            "excluded_repositories": filters.excluded_repositories,
            "excluded_repository_names": filters.excluded_repository_names,
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
        failed = owner_discovery_failed or failed_repository_count > 0 or failed_skill_count > 0
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
            repository_iterator = iter_repositories(
                filters,
                discovery_stats,
                recursive=bool(getattr(args, "recursive", False)),
                subfolder=subfolder,
            ).__aiter__()
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
                    "filtered_repository_count": listed_repository_count - active_repository_count,
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
                skill_paths = discover_skill_paths(
                    tree,
                    recursive=bool(getattr(args, "recursive", False)),
                    subfolder=subfolder,
                )
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
            planned_skill_imports: list[PlannedSkillImport] = []
            attempted_repository_bytes = 0
            repository_failed = False
            for skill_path in skill_paths:
                try:
                    planned_skill, attempted_repository_bytes = await plan_skill_import(
                        client=client,
                        repo=repo,
                        ref=resolved_ref,
                        tree=tree,
                        skill_path=skill_path,
                        import_subfolder=subfolder,
                        current_repository_bytes=attempted_repository_bytes,
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
                planned_skill_imports.append(planned_skill)

            if repository_failed or not planned_skill_imports:
                continue
            planned_skill_imports, slug_collisions = disambiguate_planned_skill_slugs(
                planned_skill_imports
            )
            if slug_collisions:
                logger.warning(
                    "github skills import slug collisions disambiguated",
                    extra={
                        **repo_context,
                        "resolved_ref": resolved_ref,
                        "collision_group_count": len(slug_collisions),
                        "collision_skill_count": sum(
                            len(paths) for paths in slug_collisions.values()
                        ),
                        "collision_slugs": list(slug_collisions)[:MAX_LOGGED_SKILL_PATHS],
                        "collision_slugs_truncated": (
                            len(slug_collisions) > MAX_LOGGED_SKILL_PATHS
                        ),
                    },
                )

            saved_records: list[SavedImportedSkill] = []
            repository_bytes = 0
            for planned_skill in planned_skill_imports:
                skill_path = planned_skill.skill_path
                try:
                    bundle_items = skill_bundle_tree_items(
                        tree,
                        skill_path=skill_path,
                    )
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
                        bundle_items=bundle_items,
                        resolved_slug=planned_skill.slug,
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

                try:
                    saved_record = await save_imported_skill(imported_skill)
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
                except Exception:
                    logger.exception(
                        "github skills import database failed",
                        extra={
                            **repo_context,
                            "resolved_ref": resolved_ref,
                            "source_path": skill_path,
                        },
                    )
                    raise

                saved_records.append(saved_record)
                imported_skill_count += 1
                imported_bytes += imported_skill.bundle_size
                logger.info(
                    "github skill import saved skill",
                    extra={
                        **repo_context,
                        "resolved_ref": resolved_ref,
                        "skill_id": saved_record.skill_id,
                        "source_path": saved_record.source_path,
                        "snapshot_hash": saved_record.content_hash,
                    },
                )

            if repository_failed or not saved_records:
                continue
            imported_repository_count += 1

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


def run_import_github_command(
    args: argparse.Namespace,
    *,
    importer: Callable[[argparse.Namespace], Awaitable[int]] | None = None,
) -> int:
    return run_github_command_with_audit(args, operation=importer or import_github_from_args)


def run_refresh_github_command(
    args: argparse.Namespace,
    *,
    refresher: Callable[[argparse.Namespace], Awaitable[int]] | None = None,
) -> int:
    return run_github_command_with_audit(args, operation=refresher or refresh_github_from_args)


def run_github_command_with_audit(
    args: argparse.Namespace,
    *,
    operation: Callable[[argparse.Namespace], Awaitable[int]],
) -> int:
    audit_enabled = get_settings().skill_audit_enabled

    async def run_operation() -> int:
        status = await operation(args)
        if audit_enabled:
            # GitHub operations use the process-wide async engine. Dispose its pool on
            # this event loop before the synchronous audit client opens a fresh loop.
            await engine.dispose()
        return status

    operation_status = asyncio.run(run_operation())
    if not audit_enabled:
        return operation_status

    # Import lazily to avoid the audit module's dependency on this module while it
    # validates bundle hashes.
    from app.cli.audit_skills import audit_pending_skill_snapshots

    audit_status = audit_pending_skill_snapshots()
    return 1 if operation_status or audit_status else 0


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
    removed = 0
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
        succeeded = updated + unchanged + removed
        logger.info(
            "github skills refresh completed",
            extra={
                "skill_count": total,
                "refreshed_skill_count": succeeded,
                "updated_skill_count": updated,
                "unchanged_skill_count": unchanged,
                "removed_skill_count": removed,
                "failed_skill_count": failed,
                "skill_bundle_bytes": refreshed_bytes,
            },
        )
        print(
            f"refreshed {succeeded} of {total} GitHub skill(s): "
            f"{updated} updated, {unchanged} unchanged, {removed} removed, {failed} failed"
        )
        return 1 if failed else 0

    def abort_refresh(exc: Exception) -> int:
        nonlocal failed
        failed = total - updated - unchanged - removed
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
                            bundle = await fetch_skill_bundle(
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

                        if bundle.resolution_status != "complete":
                            try:
                                await remove_incomplete_refreshed_skill(target)
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
                                        "failure_stage": "remove-incomplete",
                                    },
                                )
                                continue
                            removed += 1
                            refreshed_bytes += bundle.bundle_size
                            logger.warning(
                                "github skill refresh removed incomplete skill",
                                extra={
                                    "skill_id": target.id,
                                    "source": target.source,
                                    "source_path": target.skill_path,
                                    "requested_ref": requested_ref,
                                    "resolved_ref": resolved_ref,
                                    "skill_file_count": len(bundle.files),
                                    "skill_bundle_bytes": bundle.bundle_size,
                                    "skill_resolution_issue_count": len(bundle.resolution_issues),
                                    "failure_reason": "; ".join(
                                        issue["reason"]
                                        for issue in bundle.resolution_issues
                                        if issue["required"]
                                    )[:GITHUB_ERROR_BODY_MAX_CHARS],
                                },
                            )
                            continue

                        try:
                            snapshot_hash, changed = await save_refreshed_skill(
                                target,
                                bundle=bundle,
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
                        refreshed_bytes += bundle.bundle_size
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
                                "skill_file_count": len(bundle.files),
                                "skill_bundle_bytes": bundle.bundle_size,
                                "skill_resolution_status": bundle.resolution_status,
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
        "--output",
        choices=GITHUB_IMPORT_OUTPUT_FORMATS,
        default="json",
        help="Importer log output format. Use text for tab-separated human-readable logs.",
    )
    parser.add_argument(
        "--subfolder",
        default=None,
        type=import_subfolder_argument,
        help=(
            "Repository subfolder containing SKILL.md. "
            "When omitted, the repository root is the selected scope."
        ),
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help=(
            "Import every SKILL.md under the selected scope. With --subfolder, recursion "
            "is limited to that subfolder; otherwise it scans the whole repository."
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
        "--repo-name",
        dest="repository_names",
        action="append",
        default=[],
        type=github_repository_name_argument,
        help=(
            "Only repositories whose name matches this term. Repeat to require several name terms."
        ),
    )
    parser.add_argument(
        "--exclude-org",
        dest="excluded_organizations",
        action="append",
        default=[],
        type=github_owner_argument,
        help="Exclude repositories owned by this GitHub organization. Repeat as needed.",
    )
    parser.add_argument(
        "--exclude-user",
        dest="excluded_users",
        action="append",
        default=[],
        type=github_owner_argument,
        help="Exclude repositories owned by this GitHub user. Repeat as needed.",
    )
    parser.add_argument(
        "--exclude-existing-owners",
        action="store_true",
        help=(
            "Automatically exclude every GitHub user or organization that already owns "
            "a skill in Hub."
        ),
    )
    parser.add_argument(
        "--exclude-repo",
        dest="excluded_repositories",
        action="append",
        default=[],
        type=github_repository_argument,
        help="Exclude this GitHub repository in owner/repo form. Repeat as needed.",
    )
    parser.add_argument(
        "--exclude-repo-name",
        dest="excluded_repository_names",
        action="append",
        default=[],
        type=github_repository_name_argument,
        help="Exclude repositories whose name contains this term. Repeat as needed.",
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
            return run_import_github_command(args)
        except SkillCliError as exc:
            parser.error(str(exc))
    if args.command == "refresh":
        try:
            configure_logging()
            return run_refresh_github_command(args)
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
