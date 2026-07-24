from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.jobs import tasks
from app.jobs.schedules import DailySchedule, WeeklySchedule

JobRunner = Callable[[asyncio.Event], Awaitable[None]]


@dataclass(frozen=True)
class JobDefinition:
    name: str
    description: str
    run: JobRunner


def build_job_definitions(settings: Settings) -> tuple[JobDefinition, ...]:
    timezone = ZoneInfo(settings.worker_schedule_timezone)
    registry_sync_schedule = DailySchedule(
        hour=settings.worker_registry_sync_hour,
        minute=settings.worker_registry_sync_minute,
        timezone=timezone,
    )
    skill_refresh_schedule = WeeklySchedule(
        weekday=settings.worker_skill_refresh_weekday,
        hour=settings.worker_skill_refresh_hour,
        minute=settings.worker_skill_refresh_minute,
        timezone=timezone,
    )
    return (
        JobDefinition(
            name="events",
            description="Create and dispatch due event deliveries.",
            run=lambda stop: tasks.run_events(stop, settings=settings),
        ),
        JobDefinition(
            name="submission-review",
            description="Review and moderate submitted MCP server definitions.",
            run=lambda stop: tasks.run_submission_reviews(stop, settings=settings),
        ),
        JobDefinition(
            name="submission-repair",
            description="Repair eligible draft and rejected submissions.",
            run=lambda stop: tasks.run_submission_repairs(stop, settings=settings),
        ),
        JobDefinition(
            name="mcp-registry-sync",
            description="Import daily changes from the official MCP registry.",
            run=lambda stop: tasks.run_mcp_registry_sync(
                stop,
                settings=settings,
                schedule=registry_sync_schedule,
            ),
        ),
        JobDefinition(
            name="skill-maintenance",
            description="Audit pending skill snapshots and refresh GitHub sources weekly.",
            run=lambda stop: tasks.run_skill_maintenance(
                stop,
                settings=settings,
                refresh_schedule=skill_refresh_schedule,
            ),
        ),
    )


def select_job_definitions(
    jobs: Iterable[JobDefinition],
    selected_names: Iterable[str],
) -> tuple[JobDefinition, ...]:
    available = {job.name: job for job in jobs}
    requested = tuple(dict.fromkeys(name.strip() for name in selected_names if name.strip()))
    if not requested:
        return tuple(available.values())
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise ValueError(f"unknown worker jobs: {', '.join(unknown)}")
    return tuple(available[name] for name in requested)
