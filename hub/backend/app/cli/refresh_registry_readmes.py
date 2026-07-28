from __future__ import annotations

import argparse
import asyncio
import copy
from dataclasses import dataclass
from typing import Any

from app.cli.sync_mcp_registry import official_registry_documentation
from app.modules.imports.exceptions import SourceNotFoundError, UnsupportedSourceError
from app.modules.imports.service import (
    clean_subfolder,
    fetch_github_readme,
    github_source_subfolder,
    parse_github_repository,
)
from app.modules.registry import repository
from app.modules.registry.models import RegistryServer, RegistryServerVersion

DEFAULT_BATCH_SIZE = 50


class ReadmeFetchError(Exception):
    pass


@dataclass
class RefreshStats:
    seen: int = 0
    updated_readme: int = 0
    updated_generated: int = 0
    unchanged_readme: int = 0
    unchanged_generated: int = 0
    failed: int = 0

    @property
    def updated(self) -> int:
        return self.updated_readme + self.updated_generated

    @property
    def unchanged(self) -> int:
        return self.unchanged_readme + self.unchanged_generated


@dataclass(frozen=True)
class RefreshResult:
    name: str
    version: str
    status: str
    source: str
    reason: str = ""


def string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def repository_source(repository_value: Any) -> tuple[str, str] | None:
    if not isinstance(repository_value, dict):
        return None
    url = string_value(repository_value.get("url"))
    if not url:
        return None
    subfolder = clean_subfolder(string_value(repository_value.get("subfolder")))
    if not subfolder:
        subfolder = github_source_subfolder(url)
    return url, subfolder


def candidate_repository_values(
    server: RegistryServer,
    version: RegistryServerVersion,
) -> list[Any]:
    server_json = version.server_json if isinstance(version.server_json, dict) else {}
    candidates: list[Any] = [
        version.repository,
        server_json.get("repository"),
        server.repository,
        {"url": version.website_url},
        {"url": server.website_url},
    ]
    return candidates


def github_readme_sources(
    server: RegistryServer,
    version: RegistryServerVersion,
) -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidate_repository_values(server, version):
        source = repository_source(candidate)
        if source is None:
            continue
        url, subfolder = source
        try:
            parsed = parse_github_repository(url)
        except UnsupportedSourceError:
            continue
        key = (f"{parsed.owner}/{parsed.repo}".casefold(), subfolder)
        if key in seen:
            continue
        seen.add(key)
        sources.append((url, subfolder))
    return sources


def fetch_readme_for_version(
    server: RegistryServer,
    version: RegistryServerVersion,
) -> str:
    for url, subfolder in github_readme_sources(server, version):
        try:
            parsed = parse_github_repository(url)
            readme = fetch_github_readme(parsed, subfolder)
        except (SourceNotFoundError, UnsupportedSourceError) as exc:
            raise ReadmeFetchError(str(exc) or "GitHub README could not be fetched") from exc
        if readme.strip():
            return readme
    return ""


def generated_documentation(version: RegistryServerVersion) -> str:
    payload = copy.deepcopy(version.server_json if isinstance(version.server_json, dict) else {})
    payload.setdefault("description", version.description)
    if version.packages:
        payload["packages"] = copy.deepcopy(version.packages)
    else:
        payload.setdefault("packages", [])
    if version.remotes:
        payload["remotes"] = copy.deepcopy(version.remotes)
    else:
        payload.setdefault("remotes", [])
    return official_registry_documentation(payload)


def apply_documentation(
    server: RegistryServer,
    version: RegistryServerVersion,
    documentation: str,
) -> None:
    version.documentation = documentation
    server_json = copy.deepcopy(
        version.server_json if isinstance(version.server_json, dict) else {}
    )
    server_json["documentation"] = documentation
    version.server_json = server_json
    if version.is_latest and server.current_version_id == version.id:
        server.documentation = documentation


def refresh_server_version(
    server: RegistryServer,
    version: RegistryServerVersion,
    *,
    write: bool,
) -> RefreshResult:
    try:
        readme = fetch_readme_for_version(server, version)
    except ReadmeFetchError as exc:
        return RefreshResult(
            name=version.name,
            version=version.version,
            status="failed",
            source="readme",
            reason=str(exc),
        )

    source = "readme" if readme.strip() else "generated"
    documentation = readme if source == "readme" else generated_documentation(version)
    if version.documentation == documentation:
        return RefreshResult(
            name=version.name,
            version=version.version,
            status="unchanged",
            source=source,
        )

    if write:
        apply_documentation(server, version, documentation)
    return RefreshResult(
        name=version.name,
        version=version.version,
        status="updated",
        source=source,
    )


def record_result(stats: RefreshStats, result: RefreshResult) -> None:
    stats.seen += 1
    if result.status == "failed":
        stats.failed += 1
    elif result.status == "updated" and result.source == "readme":
        stats.updated_readme += 1
    elif result.status == "updated":
        stats.updated_generated += 1
    elif result.source == "readme":
        stats.unchanged_readme += 1
    else:
        stats.unchanged_generated += 1


def print_result(result: RefreshResult) -> None:
    message = (
        f"{result.status}: name={result.name} version={result.version} "
        f"source={result.source}"
    )
    if result.reason:
        message += f" reason={result.reason}"
    print(message, flush=True)


async def refresh_published_readmes(
    *,
    write: bool,
    offset: int,
    limit: int | None,
    batch_size: int,
    sleep_seconds: float,
    verbose: bool,
) -> RefreshStats:
    from app.db.session import AsyncSessionLocal

    stats = RefreshStats()
    processed = 0
    cursor = max(0, offset)
    async with AsyncSessionLocal() as session:
        while True:
            remaining = None if limit is None else max(limit - processed, 0)
            if remaining == 0:
                break
            page_size = batch_size if remaining is None else min(batch_size, remaining)
            records, total = await repository.list_published_servers(
                session,
                offset=cursor,
                limit=page_size,
            )
            if not records:
                break
            for server, version in records:
                result = refresh_server_version(server, version, write=write)
                record_result(stats, result)
                if verbose or result.status in {"failed", "updated"}:
                    print_result(result)
                if sleep_seconds > 0:
                    await asyncio.sleep(sleep_seconds)
            processed += len(records)
            cursor += len(records)
            if write:
                await session.commit()
            else:
                await session.rollback()
            if cursor >= total:
                break
    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.refresh_registry_readmes",
        description=(
            "Refresh published registry documentation from GitHub README files. "
            "When no GitHub README is available, use the generated registry fallback."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Apply database updates. Without this flag, only report the planned changes.",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Published server offset to start at.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum servers to process.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Published servers to load per database batch. Defaults to {DEFAULT_BATCH_SIZE}.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Delay between GitHub README fetches. Useful when avoiding rate limits.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print unchanged records too.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.offset < 0:
        parser.error("--offset must be greater than or equal to 0")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be greater than 0")
    if args.batch_size < 1 or args.batch_size > 500:
        parser.error("--batch-size must be between 1 and 500")
    if args.sleep_seconds < 0:
        parser.error("--sleep-seconds must be greater than or equal to 0")

    try:
        stats = asyncio.run(
            refresh_published_readmes(
                write=args.write,
                offset=args.offset,
                limit=args.limit,
                batch_size=args.batch_size,
                sleep_seconds=args.sleep_seconds,
                verbose=args.verbose,
            )
        )
    finally:
        from app.db.session import engine

        asyncio.run(engine.dispose())

    print(
        "refresh registry readmes: "
        f"seen={stats.seen} updated={stats.updated} unchanged={stats.unchanged} "
        f"updated_readme={stats.updated_readme} updated_generated={stats.updated_generated} "
        f"unchanged_readme={stats.unchanged_readme} "
        f"unchanged_generated={stats.unchanged_generated} failed={stats.failed}",
        flush=True,
    )
    return 1 if stats.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
