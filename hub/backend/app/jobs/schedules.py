from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalized_now(now: datetime | None) -> datetime:
    value = now or utc_now()
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class DailySchedule:
    hour: int
    minute: int
    timezone: ZoneInfo

    def next_after(self, now: datetime | None = None) -> datetime:
        local_now = normalized_now(now).astimezone(self.timezone)
        candidate = local_now.replace(
            hour=self.hour,
            minute=self.minute,
            second=0,
            microsecond=0,
        )
        if candidate <= local_now:
            candidate += timedelta(days=1)
        return candidate.astimezone(UTC)


@dataclass(frozen=True)
class WeeklySchedule:
    weekday: int
    hour: int
    minute: int
    timezone: ZoneInfo

    def next_after(self, now: datetime | None = None) -> datetime:
        local_now = normalized_now(now).astimezone(self.timezone)
        days_until = (self.weekday - local_now.weekday()) % 7
        candidate = (local_now + timedelta(days=days_until)).replace(
            hour=self.hour,
            minute=self.minute,
            second=0,
            microsecond=0,
        )
        if candidate <= local_now:
            candidate += timedelta(days=7)
        return candidate.astimezone(UTC)
