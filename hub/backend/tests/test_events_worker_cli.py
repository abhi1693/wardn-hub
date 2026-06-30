from __future__ import annotations

import pytest

from app.cli import events_worker


class StopWorker(Exception):
    pass


def test_next_poll_interval_backs_off_idle_batches() -> None:
    sleep_interval, next_idle_interval = events_worker.next_poll_interval(
        deliveries_created=0,
        deliveries_sent=0,
        active_interval=5,
        idle_interval=30,
        idle_min_interval=30,
        idle_max_interval=60,
    )

    assert sleep_interval == 30
    assert next_idle_interval == 60

    sleep_interval, next_idle_interval = events_worker.next_poll_interval(
        deliveries_created=0,
        deliveries_sent=0,
        active_interval=5,
        idle_interval=60,
        idle_min_interval=30,
        idle_max_interval=60,
    )

    assert sleep_interval == 60
    assert next_idle_interval == 60


def test_next_poll_interval_resets_when_work_is_processed() -> None:
    sleep_interval, next_idle_interval = events_worker.next_poll_interval(
        deliveries_created=1,
        deliveries_sent=0,
        active_interval=5,
        idle_interval=60,
        idle_min_interval=30,
        idle_max_interval=60,
    )

    assert sleep_interval == 5
    assert next_idle_interval == 30


@pytest.mark.asyncio
async def test_run_worker_adaptively_backs_off_and_resets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batches = iter(
        [
            (0, 0),
            (0, 0),
            (1, 0),
            (0, 0),
        ]
    )
    sleep_intervals: list[float] = []

    async def fake_run_once(*, limit: int) -> tuple[int, int]:
        assert limit == 50
        return next(batches)

    async def fake_sleep(interval: float) -> None:
        sleep_intervals.append(interval)
        if len(sleep_intervals) == 4:
            raise StopWorker

    monkeypatch.setattr(events_worker, "run_once", fake_run_once)
    monkeypatch.setattr(events_worker.asyncio, "sleep", fake_sleep)

    with pytest.raises(StopWorker):
        await events_worker.run_worker(
            once=False,
            limit=50,
            interval=5,
            idle_min_interval=30,
            idle_max_interval=60,
        )

    assert sleep_intervals == [30, 60, 5, 30]
