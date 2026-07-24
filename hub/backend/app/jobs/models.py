from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
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


class WorkerItemState(TimestampMixin, Base):
    __tablename__ = "worker_item_states"
    __table_args__ = (
        Index(
            "ix_worker_item_states_job_retry_claim",
            "job_name",
            "retry_after",
            "claimed_until",
        ),
    )

    job_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    claim_token: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    item_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    item_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    claimed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    retry_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_result: Mapped[str] = mapped_column(
        String(32),
        default="claimed",
        nullable=False,
    )
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
