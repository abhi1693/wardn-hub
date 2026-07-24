from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class ScheduledJobState(TimestampMixin, Base):
    __tablename__ = "scheduled_job_states"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_status: Mapped[str] = mapped_column(
        String(32),
        default="scheduled",
        nullable=False,
    )
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
