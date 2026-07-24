from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.models import ScheduledJobState


async def ensure_scheduled_job(
    session: AsyncSession,
    *,
    name: str,
    initial_next_run_at: datetime,
) -> ScheduledJobState:
    await session.execute(
        insert(ScheduledJobState)
        .values(
            name=name,
            next_run_at=initial_next_run_at,
            last_status="scheduled",
            last_error="",
        )
        .on_conflict_do_nothing(index_elements=[ScheduledJobState.name])
    )
    result = await session.execute(
        select(ScheduledJobState).where(ScheduledJobState.name == name)
    )
    return result.scalar_one()


async def mark_scheduled_job_started(
    session: AsyncSession,
    *,
    name: str,
) -> None:
    await session.execute(
        update(ScheduledJobState)
        .where(ScheduledJobState.name == name)
        .values(
            last_started_at=func.now(),
            last_status="running",
            last_error="",
        )
    )


async def mark_scheduled_job_finished(
    session: AsyncSession,
    *,
    name: str,
    next_run_at: datetime,
    return_code: int,
) -> None:
    await session.execute(
        update(ScheduledJobState)
        .where(ScheduledJobState.name == name)
        .values(
            next_run_at=next_run_at,
            last_finished_at=func.now(),
            last_status="completed" if return_code == 0 else "failed",
            last_error="" if return_code == 0 else f"command exited {return_code}",
        )
    )
