from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.config import Settings
from app.db.session import engine
from app.jobs.registry import JobDefinition
from app.jobs.tasks import wait_for_stop
from app.modules.metrics import service as metrics_service

logger = logging.getLogger(__name__)

LOCK_NAME_PREFIX = "wardn-hub:worker:"
TRY_LOCK_STATEMENT = text(
    "SELECT pg_try_advisory_lock(hashtextextended(:lock_name, 0))"
)
UNLOCK_STATEMENT = text(
    "SELECT pg_advisory_unlock(hashtextextended(:lock_name, 0))"
)
BACKEND_PID_STATEMENT = text("SELECT pg_backend_pid()")


def lock_name(job_name: str) -> str:
    return f"{LOCK_NAME_PREFIX}{job_name}"


async def database_backend_pid(connection: AsyncConnection) -> int:
    return int((await connection.execute(BACKEND_PID_STATEMENT)).scalar_one())


async def try_acquire_job_lock(
    connection: AsyncConnection,
    job_name: str,
) -> bool:
    return bool(
        (
            await connection.execute(
                TRY_LOCK_STATEMENT,
                {"lock_name": lock_name(job_name)},
            )
        ).scalar_one()
    )


async def release_job_lock(connection: AsyncConnection, job_name: str) -> None:
    await connection.execute(
        UNLOCK_STATEMENT,
        {"lock_name": lock_name(job_name)},
    )


async def run_owned_job(
    job: JobDefinition,
    *,
    stop: asyncio.Event,
    retry_seconds: float,
) -> None:
    while not stop.is_set():
        try:
            await job.run(stop)
            if not stop.is_set():
                raise RuntimeError("worker job stopped unexpectedly")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "worker job failed; restarting",
                extra={"worker_job": job.name},
            )
        if not stop.is_set():
            await wait_for_stop(stop, retry_seconds)


async def run_coordinator_session(
    jobs: tuple[JobDefinition, ...],
    *,
    stop: asyncio.Event,
    settings: Settings,
    db_engine: AsyncEngine,
) -> None:
    owned: dict[str, tuple[JobDefinition, asyncio.Task[None]]] = {}
    async with db_engine.connect() as connection:
        backend_pid = await database_backend_pid(connection)
        await connection.commit()
        try:
            while True:
                if not stop.is_set():
                    for job in jobs:
                        if job.name in owned:
                            continue
                        if not await try_acquire_job_lock(connection, job.name):
                            continue
                        metrics_service.set_worker_job_lock_held(job.name, held=True)
                        logger.info(
                            "worker job lane acquired",
                            extra={
                                "worker_job": job.name,
                                "database_backend_pid": backend_pid,
                            },
                        )
                        owned[job.name] = (
                            job,
                            asyncio.create_task(
                                run_owned_job(
                                    job,
                                    stop=stop,
                                    retry_seconds=settings.worker_lock_retry_seconds,
                                ),
                                name=f"wardn-worker-job-{job.name}",
                            ),
                        )
                    await connection.commit()

                if stop.is_set() and all(task.done() for _job, task in owned.values()):
                    return

                delay = min(
                    settings.worker_lock_retry_seconds,
                    settings.worker_lock_heartbeat_seconds,
                )
                if stop.is_set():
                    await asyncio.sleep(delay)
                else:
                    await wait_for_stop(stop, delay)
                if await database_backend_pid(connection) != backend_pid:
                    raise RuntimeError("worker coordinator database connection changed")
                await connection.commit()
        finally:
            if any(not task.done() for _job, task in owned.values()):
                for _job, task in owned.values():
                    task.cancel()
                await asyncio.gather(
                    *(task for _job, task in owned.values()),
                    return_exceptions=True,
                )
            for job_name in reversed(tuple(owned)):
                try:
                    await release_job_lock(connection, job_name)
                except Exception:
                    logger.exception(
                        "worker job lane lock release failed",
                        extra={"worker_job": job_name},
                    )
                metrics_service.set_worker_job_lock_held(job_name, held=False)
                logger.info(
                    "worker job lane released",
                    extra={"worker_job": job_name},
                )
            await connection.commit()


async def run_worker(
    jobs: tuple[JobDefinition, ...],
    *,
    stop: asyncio.Event,
    settings: Settings,
    db_engine: AsyncEngine = engine,
) -> None:
    if not jobs:
        raise ValueError("at least one worker job must be selected")
    for job in jobs:
        metrics_service.set_worker_job_lock_held(job.name, held=False)

    singleton_jobs = tuple(job for job in jobs if job.singleton)
    replicated_jobs = tuple(job for job in jobs if not job.singleton)

    async with asyncio.TaskGroup() as group:
        if singleton_jobs:
            group.create_task(
                run_singleton_jobs(
                    singleton_jobs,
                    stop=stop,
                    settings=settings,
                    db_engine=db_engine,
                ),
                name="wardn-worker-singleton-coordinator",
            )
        for job in replicated_jobs:
            logger.info(
                "worker replicated job lane started",
                extra={"worker_job": job.name},
            )
            group.create_task(
                run_owned_job(
                    job,
                    stop=stop,
                    retry_seconds=settings.worker_lock_retry_seconds,
                ),
                name=f"wardn-worker-replicated-job-{job.name}",
            )


async def run_singleton_jobs(
    jobs: tuple[JobDefinition, ...],
    *,
    stop: asyncio.Event,
    settings: Settings,
    db_engine: AsyncEngine,
) -> None:
    while not stop.is_set():
        try:
            await run_coordinator_session(
                jobs,
                stop=stop,
                settings=settings,
                db_engine=db_engine,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("worker coordinator failed; reconnecting")
            await wait_for_stop(stop, settings.worker_lock_retry_seconds)
