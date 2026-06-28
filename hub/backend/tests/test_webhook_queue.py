from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.cli.webhook_queue import RedisReliableWebhookQueue, serialize_job


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.deleted: list[str] = []

    def ping(self) -> bool:
        return True

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        _ = ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, key: str) -> int:
        self.deleted.append(key)
        return 1 if self.values.pop(key, None) is not None else 0

    def lpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    def brpoplpush(self, source: str, destination: str, timeout: int = 0) -> str | None:
        _ = timeout
        return self.rpoplpush(source, destination)

    def rpoplpush(self, source: str, destination: str) -> str | None:
        source_list = self.lists.setdefault(source, [])
        if not source_list:
            return None
        value = source_list.pop()
        self.lists.setdefault(destination, []).insert(0, value)
        return value

    def lrem(self, key: str, count: int, value: str) -> int:
        _ = count
        values = self.lists.setdefault(key, [])
        try:
            values.remove(value)
        except ValueError:
            return 0
        return 1

    def llen(self, key: str) -> int:
        return len(self.lists.setdefault(key, []))


@dataclass(frozen=True)
class ExampleJob:
    submission_id: str
    delivery_id: str
    event_id: str


def job_from_payload(payload: dict[str, Any]) -> ExampleJob:
    return ExampleJob(
        submission_id=str(payload.get("submission_id") or ""),
        delivery_id=str(payload.get("delivery_id") or ""),
        event_id=str(payload.get("event_id") or ""),
    )


def test_redis_queue_persists_job_and_deduplicates_delivery() -> None:
    redis = FakeRedis()
    processed: list[ExampleJob] = []
    queue = RedisReliableWebhookQueue(
        name="test",
        job_from_payload=job_from_payload,
        process_job=lambda job: processed.append(job) or 0,
        log_prefix="test webhook",
        redis_client=redis,  # type: ignore[arg-type]
    )
    job = ExampleJob(submission_id="sub-1", delivery_id="delivery-1", event_id="event-1")

    assert queue.enqueue(job) is True
    assert queue.enqueue(job) is False

    assert redis.lists[queue.pending_key] == [serialize_job(job)]
    assert processed == []


def test_redis_queue_removes_processing_job_after_success() -> None:
    redis = FakeRedis()
    processed: list[ExampleJob] = []
    queue = RedisReliableWebhookQueue(
        name="test",
        job_from_payload=job_from_payload,
        process_job=lambda job: processed.append(job) or 0,
        log_prefix="test webhook",
        redis_client=redis,  # type: ignore[arg-type]
    )
    job = ExampleJob(submission_id="sub-1", delivery_id="delivery-1", event_id="event-1")
    payload = serialize_job(job)
    redis.lists[queue.processing_key] = [payload]

    queue._process_payload(payload)

    assert processed == [job]
    assert redis.lists[queue.processing_key] == []


def test_redis_queue_reclaims_interrupted_processing_jobs() -> None:
    redis = FakeRedis()
    queue = RedisReliableWebhookQueue(
        name="test",
        job_from_payload=job_from_payload,
        process_job=lambda _job: 0,
        log_prefix="test webhook",
        redis_client=redis,  # type: ignore[arg-type]
    )
    job = ExampleJob(submission_id="sub-1", delivery_id="delivery-1", event_id="event-1")
    payload = serialize_job(job)
    redis.lists[queue.processing_key] = [payload]

    queue._reclaim_interrupted_jobs()

    assert redis.lists[queue.processing_key] == []
    assert redis.lists[queue.pending_key] == [payload]
