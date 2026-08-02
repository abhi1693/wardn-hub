from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.dialects import postgresql

from app.cli import worker as worker_cli
from app.core.config import get_settings
from app.jobs import repository as job_repository
from app.jobs import tasks
from app.jobs.models import WorkerItemState
from app.jobs.registry import (
    JobDefinition,
    build_job_definitions,
    select_job_definitions,
)
from app.jobs.repository import ClaimedWorkItem
from app.jobs.schedules import DailySchedule, WeeklySchedule
from app.jobs.worker import lock_name, run_worker


class FakeResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one(self) -> object:
        return self.value

    def scalars(self) -> FakeResult:
        return self

    def first(self) -> None:
        return None


class FakeDmlResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class RecordingDmlSession:
    def __init__(self, *rowcounts: int) -> None:
        self.rowcounts = iter(rowcounts)
        self.statements: list[object] = []

    async def execute(self, statement: object) -> FakeDmlResult:
        self.statements.append(statement)
        return FakeDmlResult(next(self.rowcounts))


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


def test_weekly_schedule_respects_interval_after_matching_weekday_passes() -> None:
    schedule = WeeklySchedule(
        weekday=6,
        hour=4,
        minute=43,
        timezone=ZoneInfo("Asia/Kolkata"),
        interval_weeks=2,
    )

    before = schedule.next_after(datetime(2026, 7, 25, 22, 0, tzinfo=UTC))
    after = schedule.next_after(datetime(2026, 7, 26, 1, 0, tzinfo=UTC))

    assert before == datetime(2026, 7, 25, 23, 13, tzinfo=UTC)
    assert after == datetime(2026, 8, 8, 23, 13, tzinfo=UTC)


def test_registry_selects_all_or_named_jobs_and_rejects_unknown_names() -> None:
    jobs = build_job_definitions(get_settings())

    assert [job.name for job in jobs] == [
        "events",
        "submission-review",
        "submission-repair",
        "mcp-registry-sync",
        "skill-maintenance",
        "skill-audit-backfill",
    ]
    assert [job.name for job in jobs if not job.singleton] == [
        "skill-audit-backfill"
    ]
    assert [job.name for job in select_job_definitions(jobs, ["events", "events"])] == [
        "events"
    ]
    with pytest.raises(ValueError, match="unknown worker jobs: missing"):
        select_job_definitions(jobs, ["missing"])


def test_registry_adds_skill_import_only_when_enabled() -> None:
    settings = get_settings()

    disabled = build_job_definitions(
        settings.model_copy(update={"worker_skill_import_enabled": False})
    )
    enabled = build_job_definitions(
        settings.model_copy(update={"worker_skill_import_enabled": True})
    )

    assert "skill-import" not in {job.name for job in disabled}
    assert "skill-import" in {job.name for job in enabled}


@pytest.mark.asyncio
async def test_registry_passes_configured_skill_refresh_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    captured: list[WeeklySchedule] = []
    settings = get_settings().model_copy(
        update={"worker_skill_refresh_interval_weeks": 2}
    )
    jobs = build_job_definitions(settings)
    skill_refresh = next(job for job in jobs if job.name == "skill-maintenance")

    async def run_skill_refresh(
        _stop: asyncio.Event,
        *,
        settings: object,
        schedule: WeeklySchedule,
    ) -> None:
        assert settings is not None
        captured.append(schedule)
        stop.set()

    monkeypatch.setattr(tasks, "run_skill_refresh", run_skill_refresh)

    await skill_refresh.run(stop)

    assert captured[0].interval_weeks == 2


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
async def test_replicated_worker_lane_runs_without_database_advisory_lock() -> None:
    stop = asyncio.Event()
    started = asyncio.Event()

    class UnexpectedEngine:
        def connect(self) -> None:
            raise AssertionError("replicated job lanes must not open a coordinator connection")

    async def run(stop_event: asyncio.Event) -> None:
        started.set()
        await stop_event.wait()

    worker = asyncio.create_task(
        run_worker(
            (
                JobDefinition(
                    name="replicated",
                    description="replicated",
                    run=run,
                    singleton=False,
                ),
            ),
            stop=stop,
            settings=get_settings(),
            db_engine=UnexpectedEngine(),  # type: ignore[arg-type]
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    stop.set()
    await asyncio.wait_for(worker, timeout=1)


@pytest.mark.asyncio
async def test_submission_review_lane_runs_one_noninteractive_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    commands: list[tuple[str, ...]] = []
    finished: list[tuple[str, int]] = []
    item = ClaimedWorkItem(
        item_id="5cf92456-5a43-4669-865f-60d861cadb70",
        command_id="5cf92456-5a43-4669-865f-60d861cadb70",
        claim_token=uuid4(),
        item_revision=None,
        item_updated_at=datetime(2026, 7, 24, tzinfo=UTC),
        attempt_count=1,
    )

    async def claim_work(*, settings) -> ClaimedWorkItem:
        assert settings.worker_item_lease_seconds == 1800
        return item

    async def run_command(job_name: str, *arguments: str) -> int:
        assert job_name == "submission-review"
        commands.append(arguments)
        stop.set()
        return 0

    async def finish_work(
        claimed_item: ClaimedWorkItem,
        *,
        job_name: str,
        eligible_statuses: tuple[str, ...],
        return_code: int,
        settings,
    ) -> str:
        assert claimed_item == item
        assert eligible_statuses == ("submitted",)
        assert settings.worker_item_deferred_retry_seconds == 604800
        finished.append((job_name, return_code))
        return "deferred"

    monkeypatch.setattr(tasks, "claim_submission_review_work", claim_work)
    monkeypatch.setattr(tasks, "run_app_command", run_command)
    monkeypatch.setattr(tasks, "finish_submission_work", finish_work)

    settings = get_settings().model_copy(
        update={"worker_submission_review_concurrency": 1}
    )
    await tasks.run_submission_reviews(stop, settings=settings)

    assert len(commands) == 1
    assert "app.cli.review_pending_submissions" in commands[0]
    assert "--once" in commands[0]
    assert "--non-interactive" in commands[0]
    assert "--auto-publish" in commands[0]
    assert commands[0][commands[0].index("--submission-id") + 1] == item.item_id
    assert finished == [("submission-review", 0)]


@pytest.mark.asyncio
async def test_submission_review_consumer_moves_past_unchanged_blocker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    now = datetime(2026, 7, 24, tzinfo=UTC)
    items = [
        ClaimedWorkItem(
            item_id="0cdce04b-c661-4610-8216-452919e84730",
            command_id="0cdce04b-c661-4610-8216-452919e84730",
            claim_token=uuid4(),
            item_revision=None,
            item_updated_at=now,
            attempt_count=1,
        ),
        ClaimedWorkItem(
            item_id="86f3be8d-e1cc-4e8a-b658-794025a27b9d",
            command_id="86f3be8d-e1cc-4e8a-b658-794025a27b9d",
            claim_token=uuid4(),
            item_revision=None,
            item_updated_at=now,
            attempt_count=1,
        ),
    ]
    commands: list[str] = []
    results = iter(("deferred", "completed"))

    async def claim_work(*, settings) -> ClaimedWorkItem | None:
        del settings
        return items.pop(0) if items else None

    async def run_command(_job_name: str, *arguments: str) -> int:
        commands.append(arguments[arguments.index("--submission-id") + 1])
        return 0

    async def finish_work(*_args, **_kwargs) -> str:
        result = next(results)
        if result == "completed":
            stop.set()
        return result

    monkeypatch.setattr(tasks, "claim_submission_review_work", claim_work)
    monkeypatch.setattr(tasks, "run_app_command", run_command)
    monkeypatch.setattr(tasks, "finish_submission_work", finish_work)

    await tasks.run_submission_review_consumer(
        stop,
        settings=get_settings(),
        consumer=0,
    )

    assert commands == [
        "0cdce04b-c661-4610-8216-452919e84730",
        "86f3be8d-e1cc-4e8a-b658-794025a27b9d",
    ]


@pytest.mark.asyncio
async def test_worker_claim_queries_skip_current_leases_and_lock_rows() -> None:
    statements: list[object] = []

    class EmptySession:
        async def execute(self, statement: object) -> FakeResult:
            statements.append(statement)
            return FakeResult(None)

    session = EmptySession()
    await job_repository.claim_next_submission_review(  # type: ignore[arg-type]
        session,
        lease_seconds=1800,
    )
    await job_repository.claim_next_submission_repair(  # type: ignore[arg-type]
        session,
        lease_seconds=1800,
    )
    await job_repository.claim_next_skill_audit(  # type: ignore[arg-type]
        session,
        lease_seconds=1800,
        published_before=datetime(2026, 7, 24, tzinfo=UTC),
    )

    sql = [
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        for statement in statements
    ]
    assert all("worker_item_states" in statement for statement in sql)
    assert all("FOR UPDATE" in statement and "SKIP LOCKED" in statement for statement in sql)
    assert "worker_item_states.item_updated_at = server_submissions.updated_at" in sql[0]
    assert "worker_item_states.item_updated_at = server_submissions.updated_at" in sql[1]
    assert "worker_item_states.item_revision = skill_snapshots.content_hash" in sql[2]
    assert "skill_snapshots.published_at <=" in sql[2]
    assert "ORDER BY skill_snapshots.published_at ASC, skills.id ASC" in sql[2]


@pytest.mark.asyncio
async def test_reclaim_rotates_the_item_fencing_token() -> None:
    now = datetime(2026, 7, 24, tzinfo=UTC)
    original_token = uuid4()
    state = WorkerItemState(
        job_name="submission-review",
        item_id="3d072851-f4f3-4ea2-b2f0-cfc90f8b0a32",
        claim_token=original_token,
        item_revision=None,
        item_updated_at=now,
        attempt_count=1,
        claimed_until=now,
        retry_after=None,
        last_result="claimed",
        last_error="",
    )

    class StateSession:
        async def get(self, _model: object, _key: object) -> WorkerItemState:
            return state

        async def flush(self) -> None:
            pass

    item = await job_repository.claim_item_state(
        StateSession(),  # type: ignore[arg-type]
        job_name="submission-review",
        item_id=state.item_id,
        command_id=state.item_id,
        item_updated_at=now,
        lease_seconds=1800,
        now=now,
    )

    assert item.claim_token != original_token
    assert state.claim_token == item.claim_token
    assert state.attempt_count == 2


@pytest.mark.asyncio
async def test_completion_dml_requires_the_exact_claim_token() -> None:
    token = uuid4()
    now = datetime(2026, 7, 24, tzinfo=UTC)
    item = ClaimedWorkItem(
        item_id="3d072851-f4f3-4ea2-b2f0-cfc90f8b0a32",
        command_id="3d072851-f4f3-4ea2-b2f0-cfc90f8b0a32",
        claim_token=token,
        item_revision=None,
        item_updated_at=now,
        attempt_count=1,
    )
    session = RecordingDmlSession(1, 1)

    assert await job_repository.defer_item_state(
        session,  # type: ignore[arg-type]
        item,
        job_name="submission-review",
        retry_seconds=300,
        result="deferred",
        now=now,
    )
    assert await job_repository.delete_item_state(
        session,  # type: ignore[arg-type]
        item,
        job_name="submission-review",
    )

    statements = [
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        for statement in session.statements
    ]
    assert all("worker_item_states.claim_token" in statement for statement in statements)
    assert all(str(token) in statement for statement in statements)


@pytest.mark.asyncio
async def test_stale_submission_completion_cannot_modify_a_newer_claim() -> None:
    now = datetime(2026, 7, 24, tzinfo=UTC)
    item = ClaimedWorkItem(
        item_id="3d072851-f4f3-4ea2-b2f0-cfc90f8b0a32",
        command_id="3d072851-f4f3-4ea2-b2f0-cfc90f8b0a32",
        claim_token=uuid4(),
        item_revision=None,
        item_updated_at=now,
        attempt_count=1,
    )

    class StaleCompletionSession(RecordingDmlSession):
        async def get(self, _model: object, _key: object) -> SimpleNamespace:
            return SimpleNamespace(status="submitted", updated_at=now)

    session = StaleCompletionSession(0)

    result = await job_repository.finish_submission_item(
        session,  # type: ignore[arg-type]
        item,
        job_name="submission-review",
        eligible_statuses=("submitted",),
        return_code=0,
        deferred_retry_seconds=604800,
        error_retry_seconds=300,
        now=now,
    )

    assert result == "stale"


def test_worker_errors_use_bounded_exponential_backoff() -> None:
    first_attempt = ClaimedWorkItem(
        item_id="3d072851-f4f3-4ea2-b2f0-cfc90f8b0a32",
        command_id="3d072851-f4f3-4ea2-b2f0-cfc90f8b0a32",
        claim_token=uuid4(),
        item_revision=None,
        item_updated_at=None,
        attempt_count=1,
    )
    repeated_attempt = ClaimedWorkItem(
        item_id=first_attempt.item_id,
        command_id=first_attempt.command_id,
        claim_token=uuid4(),
        item_revision=None,
        item_updated_at=None,
        attempt_count=20,
    )

    assert (
        job_repository.error_retry_delay(
            first_attempt,
            initial_retry_seconds=300,
            maximum_retry_seconds=604800,
        )
        == 300
    )
    assert (
        job_repository.error_retry_delay(
            repeated_attempt,
            initial_retry_seconds=300,
            maximum_retry_seconds=604800,
        )
        == 604800
    )


@pytest.mark.asyncio
async def test_worker_waits_for_the_packaged_database_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    revisions = iter(("202607240001", "202607240002"))

    class RevisionConnection:
        async def execute(self, _statement: object) -> FakeResult:
            return FakeResult(next(revisions))

        async def commit(self) -> None:
            pass

    class RevisionEngine:
        def connect(self) -> FakeConnectionContext:
            return FakeConnectionContext(RevisionConnection())  # type: ignore[arg-type]

    async def no_wait(_stop: asyncio.Event, _seconds: float) -> bool:
        return False

    monkeypatch.setattr(worker_cli, "engine", RevisionEngine())
    monkeypatch.setattr(worker_cli, "wait_for_stop", no_wait)

    await worker_cli.wait_for_database_revision(
        stop,
        expected_revision="202607240002",
        retry_seconds=5,
    )


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
    finished: list[tuple[str, int]] = []
    item = ClaimedWorkItem(
        item_id="28b58eb1-092d-41be-8589-f2964314ab2b",
        command_id="owner/repository/skill",
        claim_token=uuid4(),
        item_revision="a" * 64,
        item_updated_at=None,
        attempt_count=1,
    )

    async def claim_work(*, settings) -> ClaimedWorkItem:
        assert settings.worker_item_lease_seconds == 1800
        return item

    async def run_command(job_name: str, *arguments: str) -> int:
        assert job_name == "skill-audit-backfill"
        commands.append(arguments)
        stop.set()
        return 0

    async def finish_work(
        claimed_item: ClaimedWorkItem,
        *,
        return_code: int,
        settings,
    ) -> str:
        assert claimed_item == item
        finished.append((claimed_item.command_id, return_code))
        return "completed"

    monkeypatch.setattr(tasks, "claim_skill_audit_work", claim_work)
    monkeypatch.setattr(tasks, "run_app_command", run_command)
    monkeypatch.setattr(tasks, "finish_skill_audit_work", finish_work)

    await tasks.run_skill_audit_backfill(
        stop,
        settings=get_settings(),
    )

    assert len(commands) == 1
    assert "app.manage" in commands[0]
    assert "--skill-id" in commands[0]
    assert "owner/repository/skill" in commands[0]
    assert finished == [("owner/repository/skill", 0)]


@pytest.mark.asyncio
async def test_skill_refresh_keeps_immediate_audits_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    commands: list[tuple[str, ...]] = []
    scheduled_at = datetime(2026, 7, 25, tzinfo=UTC)
    next_run = datetime(2026, 8, 1, tzinfo=UTC)

    async def scheduled_job_next_run(
        name: str,
        *,
        initial_next_run_at: datetime,
    ) -> datetime:
        assert name == "skill-refresh"
        assert initial_next_run_at == next_run
        return scheduled_at

    async def wait_for_stop(_stop: asyncio.Event, _seconds: float) -> bool:
        return False

    async def mark_started(name: str) -> None:
        assert name == "skill-refresh"

    async def run_command(job_name: str, *arguments: str) -> int:
        assert job_name == "skill-maintenance"
        commands.append(arguments)
        return 0

    async def mark_finished(
        name: str,
        *,
        next_run_at: datetime,
        return_code: int,
    ) -> None:
        assert (name, next_run_at, return_code) == ("skill-refresh", next_run, 0)
        stop.set()

    monkeypatch.setattr(tasks, "scheduled_job_next_run", scheduled_job_next_run)
    monkeypatch.setattr(tasks, "wait_for_stop", wait_for_stop)
    monkeypatch.setattr(tasks, "mark_scheduled_job_started", mark_started)
    monkeypatch.setattr(tasks, "run_app_command", run_command)
    monkeypatch.setattr(tasks, "mark_scheduled_job_finished", mark_finished)
    monkeypatch.setattr(WeeklySchedule, "next_after", lambda _self, _now=None: next_run)

    await tasks.run_skill_refresh(
        stop,
        settings=get_settings(),
        schedule=WeeklySchedule(
            weekday=6,
            hour=4,
            minute=43,
            timezone=ZoneInfo("UTC"),
        ),
    )

    assert len(commands) == 1
    assert commands[0][-3:] == ("app.manage", "skills", "refresh")


@pytest.mark.asyncio
async def test_skill_import_runs_configured_arguments_on_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    commands: list[tuple[str, ...]] = []
    scheduled_at = datetime(2026, 7, 25, tzinfo=UTC)
    next_run = datetime(2026, 8, 1, tzinfo=UTC)
    settings = get_settings().model_copy(
        update={
            "worker_skill_import_arguments": [
                "--all-github",
                "--subfolder",
                "skills",
                "--recursive",
                "--min-stars",
                "1000",
            ]
        }
    )

    async def scheduled_job_next_run(
        name: str,
        *,
        initial_next_run_at: datetime,
    ) -> datetime:
        assert name == "skill-import"
        assert initial_next_run_at == next_run
        return scheduled_at

    async def wait_for_stop(_stop: asyncio.Event, _seconds: float) -> bool:
        return False

    async def mark_started(name: str) -> None:
        assert name == "skill-import"

    async def run_command(job_name: str, *arguments: str) -> int:
        assert job_name == "skill-import"
        commands.append(arguments)
        return 1

    async def mark_finished(
        name: str,
        *,
        next_run_at: datetime,
        return_code: int,
    ) -> None:
        assert (name, next_run_at, return_code) == ("skill-import", next_run, 1)
        stop.set()

    monkeypatch.setattr(tasks, "scheduled_job_next_run", scheduled_job_next_run)
    monkeypatch.setattr(tasks, "wait_for_stop", wait_for_stop)
    monkeypatch.setattr(tasks, "mark_scheduled_job_started", mark_started)
    monkeypatch.setattr(tasks, "run_app_command", run_command)
    monkeypatch.setattr(tasks, "mark_scheduled_job_finished", mark_finished)
    monkeypatch.setattr(WeeklySchedule, "next_after", lambda _self, _now=None: next_run)

    await tasks.run_skill_import(
        stop,
        settings=settings,
        schedule=WeeklySchedule(
            weekday=5,
            hour=3,
            minute=17,
            timezone=ZoneInfo("UTC"),
        ),
    )

    assert commands == [
        (
            "-m",
            "app.manage",
            "skills",
            "import-github",
            "--all-github",
            "--subfolder",
            "skills",
            "--recursive",
            "--min-stars",
            "1000",
            "--output",
            "text",
        )
    ]
