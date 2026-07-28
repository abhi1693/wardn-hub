from __future__ import annotations

import argparse
import asyncio
import copy
from dataclasses import dataclass
from typing import Any

from app.modules.registry import repository
from app.modules.registry.models import RegistryServer, RegistryServerVersion

DEFAULT_BATCH_SIZE = 100
OFFICIAL_REGISTRY_METHOD = "official_registry"
IMPORTED_STATUS = "imported"
VERIFIED_STATUS = "verified"


@dataclass
class NamespaceRepairStats:
    seen: int = 0
    updated: int = 0
    unchanged: int = 0


@dataclass(frozen=True)
class NamespaceRepairResult:
    name: str
    version: str
    status: str
    reason: str = ""


def string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def registry_namespace_meta(server_json: Any) -> dict[str, Any]:
    if not isinstance(server_json, dict):
        return {}
    meta = server_json.get("_meta")
    if not isinstance(meta, dict):
        return {}
    registry_namespace = meta.get("registryNamespace")
    if not isinstance(registry_namespace, dict):
        return {}
    return registry_namespace


def has_official_registry_namespace(server_json: Any) -> bool:
    namespace_meta = registry_namespace_meta(server_json)
    method = string_value(
        namespace_meta.get("verificationMethod") or namespace_meta.get("method")
    ).casefold()
    return method == OFFICIAL_REGISTRY_METHOD


def repaired_server_json(server_json: Any) -> dict[str, Any]:
    repaired = copy.deepcopy(server_json if isinstance(server_json, dict) else {})
    meta = repaired.get("_meta")
    if not isinstance(meta, dict):
        meta = {}
        repaired["_meta"] = meta
    namespace_meta = meta.get("registryNamespace")
    if not isinstance(namespace_meta, dict):
        namespace_meta = {}
        meta["registryNamespace"] = namespace_meta
    namespace_meta["verificationStatus"] = IMPORTED_STATUS
    return repaired


def version_needs_repair(version: RegistryServerVersion) -> bool:
    if not has_official_registry_namespace(version.server_json):
        return False
    namespace_meta = registry_namespace_meta(version.server_json)
    metadata_status = string_value(
        namespace_meta.get("verificationStatus") or namespace_meta.get("status")
    ).casefold()
    stored_status = string_value(version.registry_namespace_verification_status).casefold()
    return metadata_status == VERIFIED_STATUS or stored_status == VERIFIED_STATUS


def repair_server_version(
    server: RegistryServer,
    version: RegistryServerVersion,
    *,
    write: bool,
) -> NamespaceRepairResult:
    if not version_needs_repair(version):
        return NamespaceRepairResult(
            name=version.name,
            version=version.version,
            status="unchanged",
        )

    if write:
        version.registry_namespace_verification_status = IMPORTED_STATUS
        version.server_json = repaired_server_json(version.server_json)
        if version.is_latest and server.current_version_id == version.id:
            server.registry_namespace_verification_status = IMPORTED_STATUS

    return NamespaceRepairResult(
        name=version.name,
        version=version.version,
        status="updated",
        reason="official_registry namespace provenance is imported, not owner verified",
    )


def record_result(stats: NamespaceRepairStats, result: NamespaceRepairResult) -> None:
    stats.seen += 1
    if result.status == "updated":
        stats.updated += 1
    else:
        stats.unchanged += 1


def print_result(result: NamespaceRepairResult) -> None:
    message = f"{result.status}: name={result.name} version={result.version}"
    if result.reason:
        message += f" reason={result.reason}"
    print(message, flush=True)


async def repair_published_namespace_statuses(
    *,
    write: bool,
    offset: int,
    limit: int | None,
    batch_size: int,
    verbose: bool,
) -> NamespaceRepairStats:
    from app.db.session import AsyncSessionLocal

    stats = NamespaceRepairStats()
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
                result = repair_server_version(server, version, write=write)
                record_result(stats, result)
                if verbose or result.status == "updated":
                    print_result(result)
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
        prog="python -m app.cli.repair_registry_namespace_statuses",
        description=(
            "Repair published official MCP registry namespace statuses from "
            "verified to imported. Official registry provenance is not namespace "
            "ownership verification."
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

    try:
        stats = asyncio.run(
            repair_published_namespace_statuses(
                write=args.write,
                offset=args.offset,
                limit=args.limit,
                batch_size=args.batch_size,
                verbose=args.verbose,
            )
        )
    finally:
        from app.db.session import engine

        asyncio.run(engine.dispose())

    print(
        "repair registry namespace statuses: "
        f"seen={stats.seen} updated={stats.updated} unchanged={stats.unchanged}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
