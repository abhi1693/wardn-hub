from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from alembic.config import Config
from alembic.script import ScriptDirectory
from prometheus_client import start_http_server
from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.telemetry import configure_telemetry
from app.db.session import engine
from app.jobs.registry import (
    build_job_definitions,
    select_job_definitions,
)
from app.jobs.tasks import wait_for_stop
from app.jobs.worker import run_worker
from app.modules.metrics.service import PROCESS_REGISTRY

logger = logging.getLogger(__name__)


def expected_database_revision() -> str:
    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    if len(heads) != 1:
        raise RuntimeError(
            "worker requires exactly one Alembic head; found "
            + (", ".join(heads) or "none")
        )
    return heads[0]


async def wait_for_database_revision(
    stop: asyncio.Event,
    *,
    expected_revision: str,
    retry_seconds: float,
) -> None:
    while not stop.is_set():
        current_revision = ""
        try:
            async with engine.connect() as connection:
                current_revision = str(
                    (
                        await connection.execute(
                            text("SELECT version_num FROM alembic_version")
                        )
                    ).scalar_one()
                )
                await connection.commit()
        except Exception:
            logger.exception(
                "worker database revision check failed; retrying",
                extra={"expected_database_revision": expected_revision},
            )
        if current_revision == expected_revision:
            logger.info(
                "worker database revision ready",
                extra={"database_revision": current_revision},
            )
            return
        if current_revision:
            logger.info(
                "worker waiting for database migrations",
                extra={
                    "database_revision": current_revision,
                    "expected_database_revision": expected_revision,
                },
            )
        await wait_for_stop(stop, retry_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.worker",
        description="Run registered Wardn Hub background jobs from one scalable worker.",
    )
    parser.add_argument(
        "--job",
        action="append",
        default=[],
        help="Run only this registered job. Repeat to select multiple jobs.",
    )
    parser.add_argument(
        "--list-jobs",
        action="store_true",
        help="List registered job names and exit.",
    )
    parser.add_argument(
        "--metrics-port",
        type=int,
        default=None,
        help=(
            "Prometheus metrics listener port. Set to 0 to disable. Defaults to "
            "$WARDN_HUB_WORKER_METRICS_PORT."
        ),
    )
    return parser


async def run_selected_jobs(job_names: list[str]) -> None:
    settings = get_settings()
    jobs = select_job_definitions(build_job_definitions(settings), job_names)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(shutdown_signal, stop.set)
    try:
        await wait_for_database_revision(
            stop,
            expected_revision=expected_database_revision(),
            retry_seconds=settings.worker_lock_retry_seconds,
        )
        if stop.is_set():
            return
        await run_worker(jobs, stop=stop, settings=settings)
    finally:
        for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(shutdown_signal)
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()
    jobs = build_job_definitions(settings)
    if args.list_jobs:
        for job in jobs:
            print(f"{job.name}\t{job.description}")
        return 0
    try:
        select_job_definitions(jobs, args.job)
    except ValueError as exc:
        parser.error(str(exc))

    metrics_port = (
        settings.worker_metrics_port
        if args.metrics_port is None
        else args.metrics_port
    )
    if metrics_port < 0 or metrics_port > 65535:
        parser.error("--metrics-port must be between 0 and 65535")

    configure_logging()
    configure_telemetry()
    if metrics_port > 0:
        start_http_server(metrics_port, registry=PROCESS_REGISTRY)
        print(f"worker: metrics listening on :{metrics_port}/metrics")

    try:
        asyncio.run(run_selected_jobs(args.job))
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
