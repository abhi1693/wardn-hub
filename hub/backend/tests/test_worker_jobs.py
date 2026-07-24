from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.config import get_settings
from app.jobs import tasks
from app.jobs.registry import (
    JobDefinition,
    build_job_definitions,
    select_job_definitions,
)
from app.jobs.schedules import DailySchedule, WeeklySchedule
from app.jobs.worker import lock_name, run_worker


class FakeResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one(self) -> object:
        return self.value


class FakeConnection:
    def __init__(self) -> None:
        self.unlocked = False
        self.commits = 0

    async def execute(self, statement, parameters=None) -> FakeResult:
        sql = str(statement)
        if "pg_try_advisory_lock" in sql:
            assert parameters == {"lock_name": "wardn-hub:worker:test"}
            return FakeResult(True)
        if "pg_advisory_unlock" in sql:
            assert parameters == {"lock_name": "wardn-hub:worker:test"}
            self.unlocked = True
            return FakeResult(True)
        if "pg_backend_pid" in sql:
            return FakeResult(4242)
        raise AssertionError(f"unexpected statement: {sql}")

    async def commit(self) -> None:
        self.commits += 1


class FakeConnectionContext:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(self, *_args) -> None:
        return None


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def connect(self) -> FakeConnectionContext:
        return FakeConnectionContext(self.connection)


def test_daily_schedule_uses_configured_timezone_and_rolls_forward() -> None:
    schedule = DailySchedule(hour=2, minute=17, timezone=ZoneInfo("Asia/Kolkata"))

    before = schedule.next_after(datetime(2026, 7, 24, 20, 0, tzinfo=UTC))
    after = schedule.next_after(datetime(2026, 7, 24, 21, 0, tzinfo=UTC))

    assert before == datetime(2026, 7, 24, 20, 47, tzinfo=UTC)
    assert after == datetime(2026, 7, 25, 20, 47, tzinfo=UTC)


def test_weekly_schedule_rolls_to_the_next_matching_weekday() -> None:
    schedule = WeeklySchedule(
        weekday=6,
        hour=4,
        minute=43,
        timezone=ZoneInfo("Asia/Kolkata"),
    )

    next_run = schedule.next_after(datetime(2026, 7, 24, 12, 0, tzinfo=UTC))

    assert next_run == datetime(2026, 7, 25, 23, 13, tzinfo=UTC)


def test_registry_selects_all_or_named_jobs_and_rejects_unknown_names() -> None:
    jobs = build_job_definitions(get_settings())

    assert [job.name for job in jobs] == [
        "events",
        "submission-review",
        "submission-repair",
        "mcp-registry-sync",
        "skill-maintenance",
    ]
    assert [job.name for job in select_job_definitions(jobs, ["events", "events"])] == [
        "events"
    ]
    with pytest.raises(ValueError, match="unknown worker jobs: missing"):
        select_job_definitions(jobs, ["missing"])


@pytest.mark.asyncio
async def test_worker_holds_and_releases_its_database_advisory_lock() -> None:
    stop = asyncio.Event()
    started = asyncio.Event()
    fake_engine = FakeEngine()
    settings = get_settings().model_copy(
        update={
            "worker_lock_retry_seconds": 0.01,
            "worker_lock_heartbeat_seconds": 0.02,
        }
    )

    async def run(stop_event: asyncio.Event) -> None:
        started.set()
        await stop_event.wait()

    worker = asyncio.create_task(
        run_worker(
            (JobDefinition(name="test", description="test", run=run),),
            stop=stop,
            settings=settings,
            db_engine=fake_engine,  # type: ignore[arg-type]
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    stop.set()
    await asyncio.wait_for(worker, timeout=1)

    assert lock_name("test") == "wardn-hub:worker:test"
    assert fake_engine.connection.unlocked is True
    assert fake_engine.connection.commits >= 3


@pytest.mark.asyncio
async def test_submission_review_lane_runs_one_noninteractive_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    commands: list[tuple[str, ...]] = []

    async def has_work() -> bool:
        return True

    async def run_command(job_name: str, *arguments: str) -> int:
        assert job_name == "submission-review"
        commands.append(arguments)
        stop.set()
        return 0

    monkeypatch.setattr(tasks, "has_submission_review_work", has_work)
    monkeypatch.setattr(tasks, "run_app_command", run_command)

    await tasks.run_submission_reviews(stop, settings=get_settings())

    assert len(commands) == 1
    assert "app.cli.review_pending_submissions" in commands[0]
    assert "--once" in commands[0]
    assert "--non-interactive" in commands[0]
    assert "--auto-publish" in commands[0]


@pytest.mark.asyncio
async def test_registry_sync_retries_once_and_persists_the_next_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    run_results = iter((1, 0))
    commands: list[tuple[str, ...]] = []
    finished: list[tuple[str, datetime, int]] = []
    scheduled_at = datetime(2026, 7, 24, 0, 0, tzinfo=UTC)
    next_run = datetime(2026, 7, 25, 0, 0, tzinfo=UTC)

    async def scheduled_job_next_run(
        name: str,
        *,
        initial_next_run_at: datetime,
    ) -> datetime:
        assert name == "mcp-registry-sync"
        assert initial_next_run_at > scheduled_at
        return scheduled_at

    async def wait_for_stop(_stop: asyncio.Event, _seconds: float) -> bool:
        return False

    async def mark_started(name: str) -> None:
        assert name == "mcp-registry-sync"

    async def run_command(job_name: str, *arguments: str) -> int:
        assert job_name == "mcp-registry-sync"
        commands.append(arguments)
        return next(run_results)

    async def mark_finished(
        name: str,
        *,
        next_run_at: datetime,
        return_code: int,
    ) -> None:
        finished.append((name, next_run_at, return_code))
        stop.set()

    schedule = DailySchedule(hour=0, minute=0, timezone=ZoneInfo("UTC"))
    monkeypatch.setattr(tasks, "scheduled_job_next_run", scheduled_job_next_run)
    monkeypatch.setattr(tasks, "wait_for_stop", wait_for_stop)
    monkeypatch.setattr(tasks, "mark_scheduled_job_started", mark_started)
    monkeypatch.setattr(tasks, "run_app_command", run_command)
    monkeypatch.setattr(tasks, "mark_scheduled_job_finished", mark_finished)
    monkeypatch.setattr(DailySchedule, "next_after", lambda _self, _now=None: next_run)

    await tasks.run_mcp_registry_sync(stop, settings=get_settings(), schedule=schedule)

    assert len(commands) == 2
    assert commands[0][commands[0].index("--url") + 1] == "http://localhost:8000"
    assert finished == [("mcp-registry-sync", next_run, 0)]


@pytest.mark.asyncio
async def test_skill_maintenance_audits_one_exact_pending_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    commands: list[tuple[str, ...]] = []
    next_refresh = datetime(2099, 1, 1, tzinfo=UTC)

    async def scheduled_job_next_run(
        name: str,
        *,
        initial_next_run_at: datetime,
    ) -> datetime:
        assert name == "skill-refresh"
        assert initial_next_run_at < next_refresh
        return next_refresh

    async def next_pending_skill_audit_id() -> str:
        return "owner/repository/skill"

    async def run_command(job_name: str, *arguments: str) -> int:
        assert job_name == "skill-maintenance"
        commands.append(arguments)
        stop.set()
        return 0

    schedule = WeeklySchedule(
        weekday=6,
        hour=4,
        minute=43,
        timezone=ZoneInfo("UTC"),
    )
    monkeypatch.setattr(tasks, "scheduled_job_next_run", scheduled_job_next_run)
    monkeypatch.setattr(tasks, "next_pending_skill_audit_id", next_pending_skill_audit_id)
    monkeypatch.setattr(tasks, "run_app_command", run_command)

    await tasks.run_skill_maintenance(
        stop,
        settings=get_settings(),
        refresh_schedule=schedule,
    )

    assert len(commands) == 1
    assert "app.manage" in commands[0]
    assert "--skill-id" in commands[0]
    assert "owner/repository/skill" in commands[0]
