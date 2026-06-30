from __future__ import annotations

import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import EventDelivery
from app.modules.submissions.models import ServerSubmission

PROCESS_REGISTRY = CollectorRegistry()

WEBHOOK_JOBS_ENQUEUED = Counter(
    "wardn_webhook_jobs_enqueued_total",
    "Webhook jobs accepted by the webhook receiver.",
    ["queue", "result"],
    registry=PROCESS_REGISTRY,
)
WEBHOOK_JOBS_PROCESSED = Counter(
    "wardn_webhook_jobs_processed_total",
    "Webhook jobs processed by webhook workers.",
    ["queue", "result"],
    registry=PROCESS_REGISTRY,
)
WEBHOOK_JOB_DURATION = Histogram(
    "wardn_webhook_job_duration_seconds",
    "Time spent processing webhook jobs.",
    ["queue"],
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 900, 1800),
    registry=PROCESS_REGISTRY,
)
EVENT_WORKER_BATCHES = Counter(
    "wardn_event_worker_batches_total",
    "Event worker batches completed.",
    ["result"],
    registry=PROCESS_REGISTRY,
)
EVENT_WORKER_DELIVERIES_CREATED = Counter(
    "wardn_event_worker_deliveries_created_total",
    "Webhook delivery rows created by the event worker.",
    registry=PROCESS_REGISTRY,
)
EVENT_WORKER_DELIVERIES_SENT = Counter(
    "wardn_event_worker_deliveries_sent_total",
    "Webhook delivery attempts processed by the event worker.",
    registry=PROCESS_REGISTRY,
)
EVENT_WORKER_BATCH_DURATION = Histogram(
    "wardn_event_worker_batch_duration_seconds",
    "Time spent in one event worker batch.",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
    registry=PROCESS_REGISTRY,
)


@dataclass(frozen=True)
class QueueDepth:
    name: str
    pending: int
    processing: int


def escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def label_text(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    values = ",".join(
        f'{key}="{escape_label_value(str(value))}"' for key, value in sorted(labels.items())
    )
    return "{" + values + "}"


def metric_line(name: str, value: int | float, labels: dict[str, str] | None = None) -> str:
    return f"{name}{label_text(labels or {})} {float(value):.6g}"


def metric_block(
    *,
    name: str,
    help_text: str,
    metric_type: str,
    samples: Iterable[str],
) -> list[str]:
    return [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} {metric_type}",
        *samples,
    ]


async def collect_database_metrics(session: AsyncSession) -> str:
    lines: list[str] = []
    lines.extend(await submission_metrics(session))
    lines.extend(await event_metrics(session))
    lines.append("")
    return "\n".join(lines)


async def submission_metrics(session: AsyncSession) -> list[str]:
    review_backlog = await session.execute(
        select(func.count())
        .select_from(ServerSubmission)
        .where(ServerSubmission.status == "submitted")
    )
    review_backlog_oldest = await session.execute(
        select(
            func.max(
                func.extract(
                    "epoch",
                    func.now()
                    - func.coalesce(
                        ServerSubmission.submitted_at,
                        ServerSubmission.updated_at,
                        ServerSubmission.created_at,
                    ),
                )
            )
        ).where(ServerSubmission.status == "submitted")
    )
    review_backlog_age_buckets = await session.execute(
        text(
            """
            SELECT bucket, count(*) AS count
            FROM (
                SELECT CASE
                    WHEN now() - coalesce(submitted_at, updated_at, created_at) < interval '1 hour'
                        THEN 'lt_1h'
                    WHEN now() - coalesce(submitted_at, updated_at, created_at) < interval '6 hours'
                        THEN '1h_6h'
                    WHEN now() - coalesce(submitted_at, updated_at, created_at)
                        < interval '24 hours'
                        THEN '6h_24h'
                    ELSE 'gte_24h'
                END AS bucket
                FROM server_submissions
                WHERE status = 'submitted'
            ) backlog
            GROUP BY bucket
            ORDER BY bucket
            """
        )
    )
    submission_events_24h = await session.execute(
        text(
            """
            SELECT replace(event_type, 'submission.', '') AS action, count(*) AS count
            FROM event_records
            WHERE event_type IN (
                'submission.created',
                'submission.submitted',
                'submission.approved',
                'submission.rejected',
                'submission.published',
                'submission.withdrawn'
            )
                AND created_at >= now() - interval '24 hours'
            GROUP BY action
            ORDER BY action
            """
        )
    )
    submission_events_7d = await session.execute(
        text(
            """
            SELECT replace(event_type, 'submission.', '') AS action, count(*) AS count
            FROM event_records
            WHERE event_type IN (
                'submission.created',
                'submission.submitted',
                'submission.approved',
                'submission.rejected',
                'submission.published',
                'submission.withdrawn'
            )
                AND created_at >= now() - interval '7 days'
            GROUP BY action
            ORDER BY action
            """
        )
    )

    lines: list[str] = []
    lines.extend(
        metric_block(
            name="wardn_submission_review_backlog_total",
            help_text="Submissions currently waiting for review.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_submission_review_backlog_total",
                    review_backlog.scalar_one() or 0,
                )
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_submission_review_backlog_oldest_age_seconds",
            help_text="Age in seconds of the oldest submitted submission waiting for review.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_submission_review_backlog_oldest_age_seconds",
                    review_backlog_oldest.scalar_one() or 0,
                )
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_submission_review_backlog_age_bucket",
            help_text="Submitted submissions waiting for review by age bucket.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_submission_review_backlog_age_bucket",
                    count,
                    {"bucket": str(bucket)},
                )
                for bucket, count in review_backlog_age_buckets.all()
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_submission_events_24h_total",
            help_text="Submission lifecycle events recorded in the last 24 hours.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_submission_events_24h_total",
                    count,
                    {"action": str(action)},
                )
                for action, count in submission_events_24h.all()
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_submission_events_7d_total",
            help_text="Submission lifecycle events recorded in the last 7 days.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_submission_events_7d_total",
                    count,
                    {"action": str(action)},
                )
                for action, count in submission_events_7d.all()
            ],
        )
    )
    return lines


async def event_metrics(session: AsyncSession) -> list[str]:
    delivery_backlog = await session.execute(
        select(EventDelivery.status, EventDelivery.destination_type, func.count())
        .where(EventDelivery.status.in_(["pending", "retrying", "running"]))
        .group_by(EventDelivery.status, EventDelivery.destination_type)
    )
    due_deliveries = await session.execute(
        select(EventDelivery.status, EventDelivery.destination_type, func.count())
        .where(
            EventDelivery.status.in_(["pending", "retrying"]),
            or_(
                EventDelivery.next_attempt_at.is_(None),
                EventDelivery.next_attempt_at <= func.now(),
            ),
        )
        .group_by(EventDelivery.status, EventDelivery.destination_type)
    )
    failed_deliveries_24h = await session.execute(
        select(EventDelivery.destination_type, func.count())
        .where(
            EventDelivery.status == "failed",
            EventDelivery.updated_at >= func.now() - text("interval '24 hours'"),
        )
        .group_by(EventDelivery.destination_type)
    )

    lines: list[str] = []
    lines.extend(
        metric_block(
            name="wardn_event_delivery_backlog_total",
            help_text="Event deliveries still requiring worker action by status and destination.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_event_delivery_backlog_total",
                    count,
                    {"status": str(status), "destination_type": str(destination_type)},
                )
                for status, destination_type, count in delivery_backlog.all()
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_event_delivery_due_total",
            help_text="Pending or retrying event deliveries due to be attempted now.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_event_delivery_due_total",
                    count,
                    {"status": str(status), "destination_type": str(destination_type)},
                )
                for status, destination_type, count in due_deliveries.all()
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_event_delivery_failures_24h_total",
            help_text="Event deliveries that failed in the last 24 hours.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_event_delivery_failures_24h_total",
                    count,
                    {"destination_type": str(destination_type)},
                )
                for destination_type, count in failed_deliveries_24h.all()
            ],
        )
    )
    return lines


def process_metrics_text(extra_lines: Iterable[str] = ()) -> str:
    base = generate_latest(PROCESS_REGISTRY).decode("utf-8").rstrip()
    additions = "\n".join(extra_lines)
    if additions:
        return f"{base}\n{additions}\n"
    return f"{base}\n"


def queue_depth_metrics(depths: Iterable[QueueDepth]) -> list[str]:
    samples = []
    for depth in depths:
        samples.append(
            metric_line(
                "wardn_webhook_queue_depth",
                depth.pending,
                {"queue": depth.name, "state": "pending"},
            )
        )
        samples.append(
            metric_line(
                "wardn_webhook_queue_depth",
                depth.processing,
                {"queue": depth.name, "state": "processing"},
            )
        )
    if not samples:
        return []
    return metric_block(
        name="wardn_webhook_queue_depth",
        help_text="Webhook queue depth by queue and state.",
        metric_type="gauge",
        samples=samples,
    )


def record_webhook_enqueue(queue_name: str, *, queued: bool) -> None:
    WEBHOOK_JOBS_ENQUEUED.labels(
        queue=queue_name,
        result="queued" if queued else "duplicate",
    ).inc()


@contextmanager
def webhook_job_timer(queue_name: str) -> Iterator[None]:
    start = time.monotonic()
    try:
        yield
    finally:
        WEBHOOK_JOB_DURATION.labels(queue=queue_name).observe(time.monotonic() - start)


def record_webhook_processed(queue_name: str, result: str) -> None:
    WEBHOOK_JOBS_PROCESSED.labels(queue=queue_name, result=result).inc()


@contextmanager
def event_worker_batch_timer() -> Iterator[None]:
    start = time.monotonic()
    try:
        yield
    finally:
        EVENT_WORKER_BATCH_DURATION.observe(time.monotonic() - start)


def record_event_worker_batch(
    *,
    result: str,
    deliveries_created: int = 0,
    deliveries_sent: int = 0,
) -> None:
    EVENT_WORKER_BATCHES.labels(result=result).inc()
    EVENT_WORKER_DELIVERIES_CREATED.inc(deliveries_created)
    EVENT_WORKER_DELIVERIES_SENT.inc(deliveries_sent)
