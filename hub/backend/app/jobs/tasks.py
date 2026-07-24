from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime

from app.cli.audit_skills import load_audit_target
from app.cli.events_worker import run_worker as run_events_worker
from app.core.config import Settings
from app.db.session import AsyncSessionLocal
from app.jobs import repository as job_repository
from app.jobs.schedules import DailySchedule, WeeklySchedule
from app.modules.metrics import service as metrics_service
from app.modules.submissions.service import (
    next_submission_for_database_review,
    next_submission_for_system_fix,
)

logger = logging.getLogger(__name__)

MCP_REGISTRY_RETRY_SECONDS = 300.0
ACTIVE_SUBMISSION_DELAY_SECONDS = 1.0


async def wait_for_stop(stop: asyncio.Event, seconds: float) -> bool:
    if stop.is_set():
        return True
    try:
        await asyncio.wait_for(stop.wait(), timeout=max(0.0, seconds))
    except TimeoutError:
        return False
    return True


async def terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=10)
    except TimeoutError:
        process.kill()
        await process.wait()


async def run_app_command(job_name: str, *arguments: str) -> int:
    command = (sys.executable, *arguments)
    logger.info(
        "worker job command starting",
        extra={"worker_job": job_name, "command_module": " ".join(arguments[:3])},
    )
    with metrics_service.worker_job_timer(job_name) as metric_state:
        process = await asyncio.create_subprocess_exec(*command)
        try:
            return_code = await process.wait()
        except asyncio.CancelledError:
            metric_state["result"] = "stopped"
            await terminate_process(process)
            raise
        if return_code != 0:
            metric_state["result"] = "nonzero"
            logger.error(
                "worker job command failed",
                extra={"worker_job": job_name, "return_code": return_code},
            )
        else:
            logger.info(
                "worker job command completed",
                extra={"worker_job": job_name},
            )
        return return_code


async def has_submission_review_work() -> bool:
    async with AsyncSessionLocal() as session:
        submission = await next_submission_for_database_review(session)
        return submission is not None


async def has_submission_repair_work() -> bool:
    async with AsyncSessionLocal() as session:
        submission = await next_submission_for_system_fix(session)
        return submission is not None


async def next_pending_skill_audit_id() -> str | None:
    async with AsyncSessionLocal() as session:
        target = await load_audit_target(
            session,
            after_skill_id=None,
            skill_id=None,
            re_audit=False,
        )
        return target.catalog_id if target is not None else None


async def scheduled_job_next_run(
    name: str,
    *,
    initial_next_run_at: datetime,
) -> datetime:
    async with AsyncSessionLocal() as session:
        state = await job_repository.ensure_scheduled_job(
            session,
            name=name,
            initial_next_run_at=initial_next_run_at,
        )
        await session.commit()
        return state.next_run_at


async def mark_scheduled_job_started(name: str) -> None:
    async with AsyncSessionLocal() as session:
        await job_repository.mark_scheduled_job_started(session, name=name)
        await session.commit()


async def mark_scheduled_job_finished(
    name: str,
    *,
    next_run_at: datetime,
    return_code: int,
) -> None:
    async with AsyncSessionLocal() as session:
        await job_repository.mark_scheduled_job_finished(
            session,
            name=name,
            next_run_at=next_run_at,
            return_code=return_code,
        )
        await session.commit()


async def run_events(stop: asyncio.Event, *, settings: Settings) -> None:
    worker = asyncio.create_task(
        run_events_worker(
            once=False,
            limit=settings.worker_events_limit,
            interval=settings.worker_events_interval_seconds,
            idle_min_interval=settings.worker_events_idle_min_interval_seconds,
            idle_max_interval=settings.worker_events_idle_max_interval_seconds,
        ),
        name="wardn-worker-events",
    )
    stopped = asyncio.create_task(stop.wait(), name="wardn-worker-events-stop")
    done, _pending = await asyncio.wait(
        {worker, stopped},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if stopped in done:
        worker.cancel()
    else:
        stopped.cancel()
    await asyncio.gather(worker, stopped, return_exceptions=True)
    if worker in done:
        exception = worker.exception()
        if exception is not None:
            raise exception


async def run_submission_reviews(stop: asyncio.Event, *, settings: Settings) -> None:
    while not stop.is_set():
        if not await has_submission_review_work():
            await wait_for_stop(stop, settings.worker_submission_poll_interval_seconds)
            continue
        return_code = await run_app_command(
            "submission-review",
            "-m",
            "app.cli.review_pending_submissions",
            "--review-timeout",
            str(settings.worker_review_timeout_seconds),
            "--once",
            "--auto-reject",
            "--auto-publish",
            "--non-interactive",
            "--verbose",
        )
        delay = (
            ACTIVE_SUBMISSION_DELAY_SECONDS
            if return_code == 0
            else settings.worker_submission_poll_interval_seconds
        )
        await wait_for_stop(stop, delay)


async def run_submission_repairs(stop: asyncio.Event, *, settings: Settings) -> None:
    while not stop.is_set():
        if not await has_submission_repair_work():
            await wait_for_stop(stop, settings.worker_submission_poll_interval_seconds)
            continue
        return_code = await run_app_command(
            "submission-repair",
            "-m",
            "app.cli.fix_rejected_submissions",
            "--review-timeout",
            str(settings.worker_review_timeout_seconds),
            "--once",
            "--verbose",
        )
        delay = (
            ACTIVE_SUBMISSION_DELAY_SECONDS
            if return_code == 0
            else settings.worker_submission_poll_interval_seconds
        )
        await wait_for_stop(stop, delay)


async def run_mcp_registry_sync(
    stop: asyncio.Event,
    *,
    settings: Settings,
    schedule: DailySchedule,
) -> None:
    while not stop.is_set():
        scheduled_at = await scheduled_job_next_run(
            "mcp-registry-sync",
            initial_next_run_at=schedule.next_after(),
        )
        if await wait_for_stop(
            stop,
            (scheduled_at - datetime.now(UTC)).total_seconds(),
        ):
            return
        await mark_scheduled_job_started("mcp-registry-sync")
        return_code = await run_app_command(
            "mcp-registry-sync",
            "-m",
            "app.cli.sync_mcp_registry",
            "--url",
            settings.worker_api_base_url,
            "--since-days",
            str(settings.worker_registry_sync_since_days),
            "--limit",
            "100",
            "--verbose",
        )
        if return_code != 0:
            if await wait_for_stop(stop, MCP_REGISTRY_RETRY_SECONDS):
                return
            return_code = await run_app_command(
                "mcp-registry-sync",
                "-m",
                "app.cli.sync_mcp_registry",
                "--url",
                settings.worker_api_base_url,
                "--since-days",
                str(settings.worker_registry_sync_since_days),
                "--limit",
                "100",
                "--verbose",
            )
        await mark_scheduled_job_finished(
            "mcp-registry-sync",
            next_run_at=schedule.next_after(),
            return_code=return_code,
        )


async def run_skill_maintenance(
    stop: asyncio.Event,
    *,
    settings: Settings,
    refresh_schedule: WeeklySchedule,
) -> None:
    next_refresh = await scheduled_job_next_run(
        "skill-refresh",
        initial_next_run_at=refresh_schedule.next_after(),
    )
    while not stop.is_set():
        now = datetime.now(UTC)
        if now >= next_refresh:
            await mark_scheduled_job_started("skill-refresh")
            return_code = await run_app_command(
                "skill-maintenance",
                "-m",
                "app.manage",
                "skills",
                "refresh",
            )
            next_refresh = refresh_schedule.next_after()
            await mark_scheduled_job_finished(
                "skill-refresh",
                next_run_at=next_refresh,
                return_code=return_code,
            )
            continue

        skill_id = await next_pending_skill_audit_id()
        if skill_id is not None:
            return_code = await run_app_command(
                "skill-maintenance",
                "-m",
                "app.manage",
                "skills",
                "audit",
                "--skill-id",
                skill_id,
                "--scanner-timeout",
                str(settings.worker_skill_audit_scanner_timeout_seconds),
            )
            if return_code != 0:
                await wait_for_stop(
                    stop,
                    settings.worker_skill_audit_poll_interval_seconds,
                )
            continue

        seconds_until_refresh = max(
            0.0,
            (next_refresh - datetime.now(UTC)).total_seconds(),
        )
        await wait_for_stop(
            stop,
            min(
                settings.worker_skill_audit_poll_interval_seconds,
                seconds_until_refresh,
            ),
        )
