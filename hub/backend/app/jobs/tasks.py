from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime

from app.cli.events_worker import run_worker as run_events_worker
from app.core.config import Settings
from app.db.session import AsyncSessionLocal
from app.jobs import repository as job_repository
from app.jobs.schedules import DailySchedule, WeeklySchedule
from app.modules.metrics import service as metrics_service

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


async def claim_submission_review_work(
    *,
    settings: Settings,
) -> job_repository.ClaimedWorkItem | None:
    async with AsyncSessionLocal() as session:
        item = await job_repository.claim_next_submission_review(
            session,
            lease_seconds=settings.worker_item_lease_seconds,
        )
        await session.commit()
        return item


async def claim_submission_repair_work(
    *,
    settings: Settings,
) -> job_repository.ClaimedWorkItem | None:
    async with AsyncSessionLocal() as session:
        item = await job_repository.claim_next_submission_repair(
            session,
            lease_seconds=settings.worker_item_lease_seconds,
        )
        await session.commit()
        return item


async def claim_skill_audit_work(
    *,
    settings: Settings,
) -> job_repository.ClaimedWorkItem | None:
    async with AsyncSessionLocal() as session:
        item = await job_repository.claim_next_skill_audit(
            session,
            lease_seconds=settings.worker_item_lease_seconds,
        )
        await session.commit()
        return item


async def finish_submission_work(
    item: job_repository.ClaimedWorkItem,
    *,
    job_name: str,
    eligible_statuses: tuple[str, ...],
    return_code: int,
    settings: Settings,
) -> str:
    async with AsyncSessionLocal() as session:
        result = await job_repository.finish_submission_item(
            session,
            item,
            job_name=job_name,
            eligible_statuses=eligible_statuses,
            return_code=return_code,
            deferred_retry_seconds=settings.worker_item_deferred_retry_seconds,
            error_retry_seconds=settings.worker_item_error_retry_seconds,
        )
        await session.commit()
        return result


async def finish_skill_audit_work(
    item: job_repository.ClaimedWorkItem,
    *,
    return_code: int,
    settings: Settings,
) -> str:
    async with AsyncSessionLocal() as session:
        result = await job_repository.finish_skill_audit_item(
            session,
            item,
            return_code=return_code,
            deferred_retry_seconds=settings.worker_item_deferred_retry_seconds,
            error_retry_seconds=settings.worker_item_error_retry_seconds,
        )
        await session.commit()
        return result


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


async def run_submission_review_consumer(
    stop: asyncio.Event,
    *,
    settings: Settings,
    consumer: int,
) -> None:
    while not stop.is_set():
        item = await claim_submission_review_work(settings=settings)
        if item is None:
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
            "--submission-id",
            item.command_id,
        )
        result = await finish_submission_work(
            item,
            job_name="submission-review",
            eligible_statuses=("submitted",),
            return_code=return_code,
            settings=settings,
        )
        metrics_service.record_worker_item_result("submission-review", result=result)
        logger.info(
            "worker item finished",
            extra={
                "worker_job": "submission-review",
                "worker_item_id": item.item_id,
                "worker_item_result": result,
                "worker_item_attempt": item.attempt_count,
                "worker_consumer": consumer,
            },
        )
        if result == "completed":
            await wait_for_stop(stop, ACTIVE_SUBMISSION_DELAY_SECONDS)


async def run_submission_reviews(stop: asyncio.Event, *, settings: Settings) -> None:
    async with asyncio.TaskGroup() as group:
        for consumer in range(settings.worker_submission_review_concurrency):
            group.create_task(
                run_submission_review_consumer(
                    stop,
                    settings=settings,
                    consumer=consumer,
                ),
                name=f"wardn-worker-submission-review-{consumer}",
            )


async def run_submission_repair_consumer(
    stop: asyncio.Event,
    *,
    settings: Settings,
    consumer: int,
) -> None:
    while not stop.is_set():
        item = await claim_submission_repair_work(settings=settings)
        if item is None:
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
            "--submission-id",
            item.command_id,
        )
        result = await finish_submission_work(
            item,
            job_name="submission-repair",
            eligible_statuses=("draft", "rejected"),
            return_code=return_code,
            settings=settings,
        )
        metrics_service.record_worker_item_result("submission-repair", result=result)
        logger.info(
            "worker item finished",
            extra={
                "worker_job": "submission-repair",
                "worker_item_id": item.item_id,
                "worker_item_result": result,
                "worker_item_attempt": item.attempt_count,
                "worker_consumer": consumer,
            },
        )
        if result == "completed":
            await wait_for_stop(stop, ACTIVE_SUBMISSION_DELAY_SECONDS)


async def run_submission_repairs(stop: asyncio.Event, *, settings: Settings) -> None:
    async with asyncio.TaskGroup() as group:
        for consumer in range(settings.worker_submission_repair_concurrency):
            group.create_task(
                run_submission_repair_consumer(
                    stop,
                    settings=settings,
                    consumer=consumer,
                ),
                name=f"wardn-worker-submission-repair-{consumer}",
            )


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

        item = await claim_skill_audit_work(settings=settings)
        if item is not None:
            return_code = await run_app_command(
                "skill-maintenance",
                "-m",
                "app.manage",
                "skills",
                "audit",
                "--skill-id",
                item.command_id,
                "--scanner-timeout",
                str(settings.worker_skill_audit_scanner_timeout_seconds),
            )
            result = await finish_skill_audit_work(
                item,
                return_code=return_code,
                settings=settings,
            )
            metrics_service.record_worker_item_result(
                "skill-maintenance",
                result=result,
            )
            logger.info(
                "worker item finished",
                extra={
                    "worker_job": "skill-maintenance",
                    "worker_item_id": item.item_id,
                    "worker_item_result": result,
                    "worker_item_attempt": item.attempt_count,
                },
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
