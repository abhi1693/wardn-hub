import argparse
import asyncio
import os

from opentelemetry import trace
from prometheus_client import start_http_server

from app.core.telemetry import configure_telemetry
from app.db.session import AsyncSessionLocal
from app.modules.events.service import dispatch_due_deliveries, process_pending_events
from app.modules.metrics import service as metrics_service

METRICS_PORT_ENV = "WARDN_HUB_EVENTS_WORKER_METRICS_PORT"
DEFAULT_METRICS_PORT = 8092
DEFAULT_IDLE_MIN_INTERVAL = 30.0
DEFAULT_IDLE_MAX_INTERVAL = 60.0


def next_poll_interval(
    *,
    deliveries_created: int,
    deliveries_sent: int,
    active_interval: float,
    idle_interval: float,
    idle_min_interval: float,
    idle_max_interval: float,
) -> tuple[float, float]:
    idle_floor = max(idle_min_interval, active_interval)
    idle_cap = max(idle_max_interval, idle_floor)
    if deliveries_created > 0 or deliveries_sent > 0:
        return active_interval, idle_floor
    return idle_interval, min(idle_interval * 2, idle_cap)


async def run_once(*, limit: int) -> tuple[int, int]:
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("events_worker.run_once") as span:
        span.set_attribute("worker.limit", limit)
        with metrics_service.event_worker_batch_timer():
            try:
                async with AsyncSessionLocal() as session:
                    deliveries_created = await process_pending_events(session, limit=limit)
                    deliveries_sent = await dispatch_due_deliveries(session, limit=limit)
                    await session.commit()
                    span.set_attribute("events.deliveries_created", deliveries_created)
                    span.set_attribute("events.deliveries_sent", deliveries_sent)
                    metrics_service.record_event_worker_batch(
                        result="success",
                        deliveries_created=deliveries_created,
                        deliveries_sent=deliveries_sent,
                    )
                    return deliveries_created, deliveries_sent
            except Exception:
                metrics_service.record_event_worker_batch(result="failed")
                raise


async def run_worker(
    *,
    once: bool,
    limit: int,
    interval: float,
    idle_min_interval: float,
    idle_max_interval: float,
) -> None:
    idle_interval = max(idle_min_interval, interval)
    while True:
        deliveries_created, deliveries_sent = await run_once(limit=limit)
        if once:
            print(f"events worker: created={deliveries_created} sent={deliveries_sent}")
            return
        sleep_interval, idle_interval = next_poll_interval(
            deliveries_created=deliveries_created,
            deliveries_sent=deliveries_sent,
            active_interval=interval,
            idle_interval=idle_interval,
            idle_min_interval=idle_min_interval,
            idle_max_interval=idle_max_interval,
        )
        print(
            f"events worker: created={deliveries_created} sent={deliveries_sent} "
            f"next_poll={sleep_interval:g}s"
        )
        await asyncio.sleep(sleep_interval)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli.events_worker")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit.")
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum records to process per batch.",
    )
    parser.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds.")
    parser.add_argument(
        "--metrics-port",
        type=int,
        default=int(os.getenv(METRICS_PORT_ENV, str(DEFAULT_METRICS_PORT))),
        help=(
            "Prometheus metrics listener port. Set to 0 to disable. "
            f"Defaults to ${METRICS_PORT_ENV} or {DEFAULT_METRICS_PORT}."
        ),
    )
    parser.add_argument(
        "--idle-min-interval",
        type=float,
        default=DEFAULT_IDLE_MIN_INTERVAL,
        help=(
            "Polling interval after the first idle batch. Defaults to "
            f"{DEFAULT_IDLE_MIN_INTERVAL:g} seconds."
        ),
    )
    parser.add_argument(
        "--idle-max-interval",
        type=float,
        default=DEFAULT_IDLE_MAX_INTERVAL,
        help=(
            "Maximum polling interval while the worker remains idle. Defaults to "
            f"{DEFAULT_IDLE_MAX_INTERVAL:g} seconds."
        ),
    )
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be greater than 0")
    if args.idle_min_interval <= 0:
        parser.error("--idle-min-interval must be greater than 0")
    if args.idle_max_interval < args.idle_min_interval:
        parser.error("--idle-max-interval must be greater than or equal to --idle-min-interval")

    configure_telemetry()
    if args.metrics_port > 0:
        start_http_server(args.metrics_port)
        print(f"events worker: metrics listening on :{args.metrics_port}/metrics")

    try:
        asyncio.run(
            run_worker(
                once=args.once,
                limit=args.limit,
                interval=args.interval,
                idle_min_interval=args.idle_min_interval,
                idle_max_interval=args.idle_max_interval,
            )
        )
    except KeyboardInterrupt:
        print("events worker: stopped")


if __name__ == "__main__":
    main()
