from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from sqlalchemy import case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import EventDelivery, EventRecord, EventRule
from app.modules.registry.models import RegistryCategory, RegistryServer, RegistryServerVersion
from app.modules.submissions.models import ServerSubmission
from app.modules.users.models import User, UserAPIToken

PROCESS_REGISTRY = CollectorRegistry()
REGISTRY_METRICS_CACHE_TTL_ENV = "WARDN_HUB_REGISTRY_METRICS_CACHE_TTL_SECONDS"
DEFAULT_REGISTRY_METRICS_CACHE_TTL_SECONDS = 300.0

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


@dataclass(frozen=True)
class CachedMetricLines:
    expires_at: float
    lines: tuple[str, ...]


_registry_metrics_cache: CachedMetricLines | None = None


def registry_metrics_cache_ttl_seconds() -> float:
    value = os.getenv(REGISTRY_METRICS_CACHE_TTL_ENV, "").strip()
    if not value:
        return DEFAULT_REGISTRY_METRICS_CACHE_TTL_SECONDS
    try:
        return max(0.0, float(value))
    except ValueError:
        return DEFAULT_REGISTRY_METRICS_CACHE_TTL_SECONDS


def clear_registry_metrics_cache() -> None:
    global _registry_metrics_cache
    _registry_metrics_cache = None


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


async def grouped_counts(
    session: AsyncSession,
    *columns: Any,
) -> list[tuple[Any, ...]]:
    result = await session.execute(select(*columns, func.count()).group_by(*columns))
    return [tuple(row) for row in result.all()]


async def collect_database_metrics(session: AsyncSession) -> str:
    lines: list[str] = []
    lines.extend(await submission_metrics(session))
    lines.extend(await cached_registry_metrics(session))
    lines.extend(await event_metrics(session))
    lines.extend(await user_metrics(session))
    lines.append("")
    return "\n".join(lines)


async def cached_registry_metrics(
    session: AsyncSession,
    *,
    now: Callable[[], float] = time.monotonic,
) -> list[str]:
    global _registry_metrics_cache

    ttl_seconds = registry_metrics_cache_ttl_seconds()
    if ttl_seconds <= 0:
        return await registry_metrics(session)

    current_time = now()
    cached = _registry_metrics_cache
    if cached is not None and cached.expires_at > current_time:
        return list(cached.lines)

    lines = await registry_metrics(session)
    _registry_metrics_cache = CachedMetricLines(
        expires_at=now() + ttl_seconds,
        lines=tuple(lines),
    )
    return lines


async def submission_metrics(session: AsyncSession) -> list[str]:
    status_rows = await grouped_counts(
        session,
        ServerSubmission.status,
        ServerSubmission.submission_type,
    )
    age_result = await session.execute(
        select(
            ServerSubmission.status,
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
            ),
        ).group_by(ServerSubmission.status)
    )
    today_result = await session.execute(
        select(ServerSubmission.status, func.count())
        .where(ServerSubmission.created_at >= func.now() - text("interval '24 hours'"))
        .group_by(ServerSubmission.status)
    )
    top_submitters = await session.execute(
        select(ServerSubmission.submitter_user_id, func.count().label("count"))
        .group_by(ServerSubmission.submitter_user_id)
        .order_by(text("count DESC"))
        .limit(10)
    )
    validation_status = func.coalesce(
        ServerSubmission.validation_result["status"].as_string(),
        "unknown",
    )
    validation_result = await session.execute(
        select(
            validation_status,
            func.count(),
        ).group_by(validation_status)
    )
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
            name="wardn_submissions_total",
            help_text="Submissions by status and submission type.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_submissions_total",
                    count,
                    {"status": str(status), "submission_type": str(submission_type)},
                )
                for status, submission_type, count in status_rows
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_submissions_created_24h_total",
            help_text="Submissions created in the last 24 hours by current status.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_submissions_created_24h_total",
                    count,
                    {"status": str(status)},
                )
                for status, count in today_result.all()
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_submission_oldest_status_age_seconds",
            help_text="Age in seconds of the oldest submission in each status.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_submission_oldest_status_age_seconds",
                    age or 0,
                    {"status": str(status)},
                )
                for status, age in age_result.all()
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_submission_validation_total",
            help_text="Submissions by validation result status.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_submission_validation_total",
                    count,
                    {"validation_status": str(status)},
                )
                for status, count in validation_result.all()
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_submission_top_submitters",
            help_text="Top submission owners by rank, without exposing user identifiers.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_submission_top_submitters",
                    count,
                    {"rank": str(index)},
                )
                for index, (_user_id, count) in enumerate(top_submitters.all(), start=1)
            ],
        )
    )
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


async def registry_metrics(session: AsyncSession) -> list[str]:
    server_status_rows = await grouped_counts(
        session,
        RegistryServer.status,
        RegistryServer.visibility,
    )
    version_status_rows = await grouped_counts(
        session,
        RegistryServerVersion.status,
        RegistryServerVersion.is_latest,
    )
    quality_bucket = case(
        (RegistryServerVersion.quality_score.is_(None), "missing"),
        (RegistryServerVersion.quality_score >= 90, "90_100"),
        (RegistryServerVersion.quality_score >= 75, "75_89"),
        (RegistryServerVersion.quality_score >= 50, "50_74"),
        else_="0_49",
    ).label("bucket")
    quality_buckets = select(quality_bucket).subquery()
    quality_rows = await session.execute(
        select(quality_buckets.c.bucket, func.count()).group_by(quality_buckets.c.bucket)
    )
    category_rows = await session.execute(
        select(RegistryCategory.status, func.count()).group_by(RegistryCategory.status)
    )
    trust_rows = await session.execute(
        text(
            """
            SELECT signal, state, count(*) AS count
            FROM (
                SELECT 'quality_score' AS signal,
                    CASE WHEN quality_score IS NULL THEN 'missing' ELSE 'present' END AS state
                FROM mcp_server_versions
                UNION ALL
                SELECT 'license' AS signal,
                    CASE
                        WHEN coalesce(server_json->>'license', '') <> ''
                            OR coalesce(server_json #>> '{_meta,license}', '') <> ''
                            OR coalesce(server_json #>> '{_meta,repository,license}', '') <> ''
                            OR coalesce(repository->>'license', '') <> ''
                            OR coalesce(repository->>'licenseSpdxId', '') <> ''
                        THEN 'present'
                        ELSE 'missing'
                    END AS state
                FROM mcp_server_versions
                UNION ALL
                SELECT 'source_review' AS signal,
                    CASE
                        WHEN server_json #> '{_meta,sourceReview}' IS NOT NULL THEN 'present'
                        ELSE 'missing'
                    END AS state
                FROM mcp_server_versions
                UNION ALL
                SELECT 'owner_verification' AS signal,
                    CASE
                        WHEN server_json #>> '{_meta,wardnOwnership,verified}' = 'true'
                        THEN 'verified'
                        WHEN owner_user_id IS NOT NULL OR owner_organization_id IS NOT NULL
                        THEN 'linked'
                        ELSE 'missing'
                    END AS state
                FROM mcp_server_versions
                UNION ALL
                SELECT 'security_review' AS signal,
                    CASE
                        WHEN server_json #> '{_meta,securityReview}' IS NOT NULL
                            OR server_json #> '{_meta,security}' IS NOT NULL
                        THEN 'present'
                        ELSE 'missing'
                    END AS state
                FROM mcp_server_versions
            ) signals
            GROUP BY signal, state
            ORDER BY signal, state
            """
        )
    )
    uncategorized = await session.execute(
        text(
            """
            SELECT count(*)
            FROM mcp_servers servers
            WHERE NOT EXISTS (
                SELECT 1
                FROM mcp_server_categories categories
                WHERE categories.server_id = servers.id
            )
            """
        )
    )

    lines: list[str] = []
    lines.extend(
        metric_block(
            name="wardn_registry_servers_total",
            help_text="Registry servers by status and visibility.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_registry_servers_total",
                    count,
                    {"status": str(status), "visibility": str(visibility)},
                )
                for status, visibility, count in server_status_rows
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_registry_versions_total",
            help_text="Registry server versions by status and latest flag.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_registry_versions_total",
                    count,
                    {"status": str(status), "is_latest": str(bool(is_latest)).lower()},
                )
                for status, is_latest, count in version_status_rows
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_registry_quality_score_bucket",
            help_text="Registry versions grouped by quality score range.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_registry_quality_score_bucket",
                    count,
                    {"bucket": str(bucket)},
                )
                for bucket, count in quality_rows.all()
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_registry_trust_signal_total",
            help_text="Trust report evidence signals across registry versions.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_registry_trust_signal_total",
                    count,
                    {"signal": str(signal), "state": str(state)},
                )
                for signal, state, count in trust_rows.all()
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_registry_categories_total",
            help_text="Registry categories by status.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_registry_categories_total",
                    count,
                    {"status": str(status)},
                )
                for status, count in category_rows.all()
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_registry_uncategorized_servers_total",
            help_text="Registry servers that have no category assignment.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_registry_uncategorized_servers_total",
                    uncategorized.scalar_one() or 0,
                )
            ],
        )
    )
    return lines


async def event_metrics(session: AsyncSession) -> list[str]:
    delivery_rows = await grouped_counts(
        session,
        EventDelivery.status,
        EventDelivery.destination_type,
    )
    event_rows = await grouped_counts(
        session,
        EventRecord.event_type,
    )
    rules_rows = await session.execute(
        select(EventRule.action_type, EventRule.is_enabled, func.count()).group_by(
            EventRule.action_type,
            EventRule.is_enabled,
        )
    )
    oldest_delivery = await session.execute(
        select(
            EventDelivery.status,
            func.max(func.extract("epoch", func.now() - EventDelivery.created_at)),
        )
        .where(EventDelivery.status.in_(["pending", "retrying", "running"]))
        .group_by(EventDelivery.status)
    )
    event_backlog = await session.execute(
        select(func.count()).select_from(EventRecord).where(EventRecord.processed_at.is_(None))
    )
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
            name="wardn_event_deliveries_total",
            help_text="Event webhook deliveries by status and destination type.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_event_deliveries_total",
                    count,
                    {"status": str(status), "destination_type": str(destination_type)},
                )
                for status, destination_type, count in delivery_rows
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_events_total",
            help_text="Event records by event type.",
            metric_type="gauge",
            samples=[
                metric_line("wardn_events_total", count, {"event_type": str(event_type)})
                for event_type, count in event_rows
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_event_rules_total",
            help_text="Event rules by action type and enabled state.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_event_rules_total",
                    count,
                    {"action_type": str(action_type), "enabled": str(bool(is_enabled)).lower()},
                )
                for action_type, is_enabled, count in rules_rows.all()
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_event_delivery_oldest_status_age_seconds",
            help_text="Age in seconds of the oldest active event delivery by status.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_event_delivery_oldest_status_age_seconds",
                    age or 0,
                    {"status": str(status)},
                )
                for status, age in oldest_delivery.all()
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_event_unprocessed_records_total",
            help_text="Event records waiting to be converted into deliveries.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_event_unprocessed_records_total",
                    event_backlog.scalar_one() or 0,
                )
            ],
        )
    )
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


async def user_metrics(session: AsyncSession) -> list[str]:
    user_rows = await session.execute(
        select(User.is_active, User.is_superuser, func.count()).group_by(
            User.is_active,
            User.is_superuser,
        )
    )
    signup_rows = await session.execute(
        select(func.count())
        .select_from(User)
        .where(User.created_at >= func.now() - text("interval '24 hours'"))
    )
    active_submitters = await session.execute(
        select(func.count(func.distinct(ServerSubmission.submitter_user_id))).where(
            ServerSubmission.created_at >= func.now() - text("interval '30 days'")
        )
    )
    token_rows = await session.execute(
        select(UserAPIToken.is_active, func.count()).group_by(UserAPIToken.is_active)
    )

    lines: list[str] = []
    lines.extend(
        metric_block(
            name="wardn_users_total",
            help_text="Users by active and superuser flags.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_users_total",
                    count,
                    {
                        "active": str(bool(is_active)).lower(),
                        "superuser": str(bool(is_superuser)).lower(),
                    },
                )
                for is_active, is_superuser, count in user_rows.all()
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_users_signed_up_24h_total",
            help_text="Users created in the last 24 hours.",
            metric_type="gauge",
            samples=[metric_line("wardn_users_signed_up_24h_total", signup_rows.scalar_one() or 0)],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_active_submitters_30d_total",
            help_text="Distinct users who created submissions in the last 30 days.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_active_submitters_30d_total",
                    active_submitters.scalar_one() or 0,
                )
            ],
        )
    )
    lines.extend(
        metric_block(
            name="wardn_api_tokens_total",
            help_text="API tokens by active state.",
            metric_type="gauge",
            samples=[
                metric_line(
                    "wardn_api_tokens_total",
                    count,
                    {"active": str(bool(is_active)).lower()},
                )
                for is_active, count in token_rows.all()
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
