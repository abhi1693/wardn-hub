from __future__ import annotations

import argparse
import asyncio
import signal

from prometheus_client import start_http_server

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.telemetry import configure_telemetry
from app.db.session import engine
from app.jobs.registry import (
    build_job_definitions,
    select_job_definitions,
)
from app.jobs.worker import run_worker
from app.modules.metrics.service import PROCESS_REGISTRY


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
