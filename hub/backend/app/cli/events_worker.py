import argparse
import asyncio

from app.db.session import AsyncSessionLocal
from app.modules.events.service import dispatch_due_deliveries, process_pending_events


async def run_once(*, limit: int) -> tuple[int, int]:
    async with AsyncSessionLocal() as session:
        deliveries_created = await process_pending_events(session, limit=limit)
        deliveries_sent = await dispatch_due_deliveries(session, limit=limit)
        await session.commit()
        return deliveries_created, deliveries_sent


async def run_worker(*, once: bool, limit: int, interval: float) -> None:
    while True:
        deliveries_created, deliveries_sent = await run_once(limit=limit)
        print(f"events worker: created={deliveries_created} sent={deliveries_sent}")
        if once:
            return
        await asyncio.sleep(interval)


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
    args = parser.parse_args()

    try:
        asyncio.run(run_worker(once=args.once, limit=args.limit, interval=args.interval))
    except KeyboardInterrupt:
        print("events worker: stopped")


if __name__ == "__main__":
    main()
