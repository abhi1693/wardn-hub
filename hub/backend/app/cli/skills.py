from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.modules.skills.models import Skill, SkillSnapshot, SkillSourceOwner

logger = logging.getLogger(__name__)

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
DEFAULT_USER_AGENT = "WardnHubSkillsImporter/0.1"
DEFAULT_IMPORT_TIMEOUT_SECONDS = 20.0
MAX_LOGGED_SKILL_PATHS = 20
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
TEXT_FILE_NAMES = {
    "AGENTS.md",
    "LICENSE",
    "README.md",
    "SKILL.md",
}
TEXT_FILE_SUFFIXES = {
    ".css",
    ".csv",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}


class SkillCliError(Exception):
    pass


class InvalidSkillTextError(SkillCliError):
    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{reason}: {path}")


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
    files: list[dict[str, str]]
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


@dataclass(frozen=True)
class GitHubRepositoryMetadata:
    default_branch: str
    owner_avatar_url: str


@dataclass(frozen=True)
class ImportedSkill:
    payload: SkillAddInput
    source_path: str


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


def snapshot_files(contents: str) -> list[dict[str, str]]:
    return [{"path": "SKILL.md", "contents": contents}]


def content_hash(files: list[dict[str, str]]) -> str:
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


async def add_skill(session: AsyncSession, payload: SkillAddInput) -> tuple[Skill, SkillSnapshot]:
    hash_value = content_hash(payload.files)
    frontmatter = parse_frontmatter(payload.skill_md)

    result = await session.execute(
        select(Skill).where(
            Skill.source_type == payload.source_type,
            Skill.source == payload.source,
            Skill.slug == payload.slug,
        )
    )
    skill = result.scalar_one_or_none()
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
        skill.status = "active"
        skill.visibility = "public"

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
            skill_md=payload.skill_md,
            metadata_=frontmatter,
            files=payload.files,
            status="active",
            is_latest=True,
        )
        session.add(snapshot)
        await session.flush()
    else:
        snapshot.skill_md = payload.skill_md
        snapshot.metadata_ = frontmatter
        snapshot.files = payload.files
        snapshot.status = "active"
        snapshot.is_latest = True

    skill.current_snapshot_id = snapshot.id
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
        self._client = httpx.AsyncClient(timeout=timeout_seconds, headers=headers)

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._client.aclose()

    async def repository_metadata(self, repo: GitHubRepository) -> GitHubRepositoryMetadata:
        response = await self._client.get(
            f"https://api.github.com/repos/{repo.owner}/{repo.repo}"
        )
        if response.status_code == 404:
            raise SkillCliError(f"GitHub repository not found: {repo.source}")
        if response.status_code >= 400:
            raise SkillCliError(f"GitHub repository lookup failed: {response.text}")
        payload = response.json()
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
        )

    async def recursive_tree(self, repo: GitHubRepository, ref: str) -> list[GitHubTreeItem]:
        response = await self._client.get(
            f"https://api.github.com/repos/{repo.owner}/{repo.repo}/git/trees/{ref}",
            params={"recursive": "1"},
        )
        if response.status_code == 404:
            raise SkillCliError(f"GitHub ref not found for {repo.source}: {ref}")
        if response.status_code >= 400:
            raise SkillCliError(f"GitHub tree lookup failed: {response.text}")
        payload = response.json()
        if payload.get("truncated") is True:
            raise SkillCliError("GitHub tree is truncated; pass --subfolder to import one skill")
        return [
            GitHubTreeItem(
                path=str(item.get("path") or ""),
                type=str(item.get("type") or ""),
                size=int(item.get("size") or 0),
            )
            for item in payload.get("tree", [])
            if isinstance(item, dict) and item.get("path")
        ]

    async def raw_file(self, repo: GitHubRepository, ref: str, path: str) -> str:
        response = await self._client.get(
            f"https://raw.githubusercontent.com/{repo.owner}/{repo.repo}/{ref}/{path}"
        )
        if response.status_code == 404:
            raise SkillCliError(f"GitHub file not found: {path}")
        if response.status_code >= 400:
            raise SkillCliError(f"GitHub raw file fetch failed for {path}: {response.text}")
        content = response.content
        nul_offset = content.find(b"\x00")
        if nul_offset >= 0:
            line_number = content.count(b"\n", 0, nul_offset) + 1
            raise InvalidSkillTextError(
                path,
                f"GitHub file contains a NUL byte at offset {nul_offset} "
                f"(line {line_number})",
            )
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidSkillTextError(path, "GitHub file is not UTF-8 text") from exc


def tree_blob_paths(tree: list[GitHubTreeItem]) -> set[str]:
    return {item.path for item in tree if item.type == "blob"}


def is_probable_text_file(path: str) -> bool:
    file_path = Path(path)
    if file_path.name in TEXT_FILE_NAMES:
        return True
    return file_path.suffix.lower() in TEXT_FILE_SUFFIXES


def should_skip_tree_path(path: str) -> bool:
    return any(part in SKIPPED_PATH_PARTS for part in Path(path).parts)


def skill_root_from_skill_path(path: str) -> str:
    parent = str(Path(path).parent)
    return "" if parent == "." else parent


def relative_skill_file_path(root: str, path: str) -> str:
    if not root:
        return path
    return str(Path(path).relative_to(root))


def discover_skill_paths(
    tree: list[GitHubTreeItem],
    *,
    subfolder: str,
) -> list[str]:
    blobs = tree_blob_paths(tree)
    if subfolder:
        skill_path = f"{subfolder}/SKILL.md"
        if skill_path in blobs:
            return [skill_path]

        prefix = f"{subfolder}/"
        skill_paths = sorted(
            item.path
            for item in tree
            if item.type == "blob"
            and item.path.startswith(prefix)
            and Path(item.path).name == "SKILL.md"
            and not should_skip_tree_path(item.path)
        )
        if not skill_paths:
            raise SkillCliError(f"No SKILL.md files found under GitHub subfolder: {subfolder}")
        return skill_paths

    skill_paths = sorted(
        item.path
        for item in tree
        if item.type == "blob"
        and Path(item.path).name == "SKILL.md"
        and not should_skip_tree_path(item.path)
    )
    if not skill_paths:
        raise SkillCliError("No SKILL.md files found in GitHub repository")
    return skill_paths


async def import_skill_from_github_path(
    *,
    client: GitHubClient,
    repo: GitHubRepository,
    ref: str,
    tree: list[GitHubTreeItem],
    skill_path: str,
    owner_avatar_url: str,
    import_subfolder: str,
    is_multi_skill_import: bool,
    args: argparse.Namespace,
) -> ImportedSkill:
    root = skill_root_from_skill_path(skill_path)
    skill_md = await client.raw_file(repo, ref, skill_path)
    files = [{"path": "SKILL.md", "contents": skill_md}]
    frontmatter = parse_frontmatter(skill_md)
    name = (args.name or frontmatter.get("name") or Path(root).name or repo.repo).strip()
    slug = validate_skill_slug(args.slug or slug_from_name(name))
    if not args.slug and is_multi_skill_import:
        slug = validate_skill_slug(
            slug_from_skill_root(skill_slug_root(root, import_subfolder), name)
        )
    description = (args.description or frontmatter.get("description") or "").strip()
    repository_url = repo.url
    if root:
        repository_url = f"{repo.url}/tree/{ref}/{root}"
    logger.info(
        "github skill import fetched skill file",
        extra={
            "source": repo.source,
            "ref": ref,
            "source_path": skill_path,
            "skill_slug": slug,
            "skill_name": name,
            "skill_root": root,
            "skill_md_bytes": len(skill_md.encode("utf-8")),
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
        install_url=args.install_url or repository_url,
        website_url=args.website_url or repository_url,
        repository_url=repo.url,
        repository_subfolder=root,
        repository_ref=ref,
    )
    return ImportedSkill(payload=payload, source_path=skill_path)


async def import_github_from_args(args: argparse.Namespace) -> int:
    repo = parse_github_repository_url(args.repository_url)
    subfolder = normalize_repo_subfolder(args.subfolder or repo.path)
    token = args.github_token or os.getenv(GITHUB_TOKEN_ENV, "")
    skipped: list[tuple[str, str]] = []
    log_context = {
        "source": repo.source,
        "repository_url": repo.url,
        "subfolder": subfolder,
        "requested_ref": args.ref or repo.ref,
        "github_token_configured": bool(token.strip()),
    }
    logger.info("github skills import started", extra=log_context)

    try:
        async with GitHubClient(token=token, timeout_seconds=args.timeout_seconds) as client:
            metadata = await client.repository_metadata(repo)
            ref = args.ref or repo.ref or metadata.default_branch
            logger.info(
                "github skills import repository resolved",
                extra={
                    **log_context,
                    "ref": ref,
                    "default_branch": metadata.default_branch,
                    "owner_avatar_url_configured": bool(metadata.owner_avatar_url),
                },
            )
            tree = await client.recursive_tree(repo, ref)
            logger.info(
                "github skills import tree fetched",
                extra={**log_context, "ref": ref, "tree_item_count": len(tree)},
            )
            skill_paths = discover_skill_paths(tree, subfolder=subfolder)
            logger.info(
                "github skills import discovered skills",
                extra={
                    **log_context,
                    "ref": ref,
                    "skill_count": len(skill_paths),
                    "skill_paths": skill_paths[:MAX_LOGGED_SKILL_PATHS],
                    "skill_paths_truncated": len(skill_paths) > MAX_LOGGED_SKILL_PATHS,
                },
            )
            if len(skill_paths) > 1 and (args.slug or args.name or args.description):
                raise SkillCliError(
                    "--slug, --name, and --description can only be used when importing one skill; "
                    "pass --subfolder to target a single skill"
                )
            imported = []
            for skill_path in skill_paths:
                try:
                    imported_skill = await import_skill_from_github_path(
                        client=client,
                        repo=repo,
                        ref=ref,
                        tree=tree,
                        skill_path=skill_path,
                        owner_avatar_url=metadata.owner_avatar_url,
                        import_subfolder=subfolder,
                        is_multi_skill_import=len(skill_paths) > 1,
                        args=args,
                    )
                except InvalidSkillTextError as exc:
                    if len(skill_paths) == 1:
                        raise
                    skipped.append((skill_path, str(exc)))
                    logger.warning(
                        "github skill import skipped invalid skill",
                        extra={
                            **log_context,
                            "ref": ref,
                            "source_path": skill_path,
                            "skip_reason": str(exc),
                        },
                    )
                    continue
                imported.append(imported_skill)

            if not imported:
                raise SkillCliError(
                    f"No valid SKILL.md files could be imported; skipped {len(skipped)} "
                    "invalid skill(s)"
                )

        async with AsyncSessionLocal() as session:
            results = []
            for item in imported:
                skill, snapshot = await add_skill(session, item.payload)
                results.append((skill, snapshot, item.source_path))
                logger.info(
                    "github skill import saved skill",
                    extra={
                        **log_context,
                        "skill_id": f"{skill.source}/{skill.slug}",
                        "source_path": item.source_path,
                        "repository_subfolder": item.payload.repository_subfolder,
                        "snapshot_hash": snapshot.content_hash,
                    },
                )
            await session.commit()
            logger.info(
                "github skills import completed",
                extra={
                    **log_context,
                    "skill_count": len(results),
                    "skipped_skill_count": len(skipped),
                    "discovered_skill_count": len(skill_paths),
                },
            )
    except Exception:
        logger.exception("github skills import failed", extra=log_context)
        raise

    for skill, snapshot, source_path in results:
        skill_id = f"{skill.source}/{skill.slug}"
        print(f"imported skill {skill_id} from {source_path}")
        print(f"snapshot {snapshot.content_hash}")
        print(f"detail /api/v1/skills/{skill_id}")
    print(f"imported {len(results)} skill(s)")
    if skipped:
        print(f"skipped {len(skipped)} invalid skill(s)")
    return 0


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
        help="Import one or more skills from a GitHub repository.",
    )
    import_parser.add_argument("repository_url", help="GitHub repository URL.")
    import_parser.add_argument(
        "--subfolder",
        default="",
        help=(
            "Optional subfolder containing one SKILL.md or nested skill folders. "
            "If omitted, all SKILL.md files are imported."
        ),
    )
    import_parser.add_argument("--ref", default="", help="Git ref, branch, tag, or SHA.")
    import_parser.add_argument(
        "--slug",
        default="",
        help="Override slug for a single imported skill.",
    )
    import_parser.add_argument(
        "--name",
        default="",
        help="Override name for a single imported skill.",
    )
    import_parser.add_argument(
        "--description",
        default="",
        help="Override description for a single imported skill.",
    )
    import_parser.add_argument("--install-url", default="", help="Install/source URL override.")
    import_parser.add_argument("--website-url", default="", help="Website or docs URL override.")
    import_parser.add_argument(
        "--github-token",
        default="",
        help=f"GitHub token. Defaults to ${GITHUB_TOKEN_ENV} when set.",
    )
    import_parser.add_argument(
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
    if args.command == "mark-official":
        try:
            return asyncio.run(mark_official_from_args(args))
        except SkillCliError as exc:
            parser.error(str(exc))
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
