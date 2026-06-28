from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Callable
from dataclasses import asdict
from typing import Any, Protocol, TypeVar

from redis import Redis
from redis.sentinel import Sentinel

from app.modules.metrics import service as metrics_service

QUEUE_BACKEND_ENV = "WARDN_HUB_WEBHOOK_QUEUE_BACKEND"
REDIS_URL_ENV = "WARDN_HUB_WEBHOOK_REDIS_URL"
REDIS_SENTINELS_ENV = "WARDN_HUB_WEBHOOK_REDIS_SENTINELS"
REDIS_SENTINEL_SERVICE_ENV = "WARDN_HUB_WEBHOOK_REDIS_SENTINEL_SERVICE"
REDIS_DB_ENV = "WARDN_HUB_WEBHOOK_REDIS_DB"
REDIS_PASSWORD_ENV = "WARDN_HUB_WEBHOOK_REDIS_PASSWORD"
REDIS_SENTINEL_PASSWORD_ENV = "WARDN_HUB_WEBHOOK_REDIS_SENTINEL_PASSWORD"
REDIS_SOCKET_TIMEOUT_ENV = "WARDN_HUB_WEBHOOK_REDIS_SOCKET_TIMEOUT_SECONDS"
REDIS_DEDUPE_TTL_ENV = "WARDN_HUB_WEBHOOK_REDIS_DEDUPE_TTL_SECONDS"
DEFAULT_REDIS_SENTINEL_SERVICE = "valkey"
DEFAULT_REDIS_DB = 40
DEFAULT_REDIS_SOCKET_TIMEOUT_SECONDS = 5.0
DEFAULT_REDIS_DEDUPE_TTL_SECONDS = 7 * 24 * 60 * 60

JobT = TypeVar("JobT")


class QueueConfigurationError(Exception):
    pass


class WebhookQueue(Protocol[JobT]):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def enqueue(self, job: JobT) -> bool: ...

    def queue_depths(self) -> list[metrics_service.QueueDepth]: ...


class QueueJob(Protocol):
    submission_id: str
    delivery_id: str
    event_id: str


def durable_queue_requested() -> bool:
    backend = os.getenv(QUEUE_BACKEND_ENV, "").strip().lower()
    if backend in {"", "memory", "in-memory", "local"}:
        return bool(
            os.getenv(REDIS_URL_ENV, "").strip()
            or os.getenv(REDIS_SENTINELS_ENV, "").strip()
        )
    if backend in {"redis", "valkey"}:
        return True
    raise QueueConfigurationError(
        f"${QUEUE_BACKEND_ENV} must be memory, redis, or valkey when set"
    )


def parse_float_env(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise QueueConfigurationError(f"${name} must be a number") from exc


def parse_int_env(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise QueueConfigurationError(f"${name} must be an integer") from exc


def parse_sentinels(value: str) -> list[tuple[str, int]]:
    sentinels: list[tuple[str, int]] = []
    for item in value.split(","):
        raw = item.strip()
        if not raw:
            continue
        host, separator, port_value = raw.rpartition(":")
        if not separator or not host or not port_value:
            raise QueueConfigurationError(
                f"${REDIS_SENTINELS_ENV} entries must use host:port"
            )
        try:
            port = int(port_value)
        except ValueError as exc:
            raise QueueConfigurationError(
                f"${REDIS_SENTINELS_ENV} entries must use numeric ports"
            ) from exc
        sentinels.append((host, port))
    return sentinels


def redis_client_from_env() -> Redis:
    socket_timeout = parse_float_env(
        REDIS_SOCKET_TIMEOUT_ENV,
        DEFAULT_REDIS_SOCKET_TIMEOUT_SECONDS,
    )
    redis_url = os.getenv(REDIS_URL_ENV, "").strip()
    if redis_url:
        return Redis.from_url(
            redis_url,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_timeout,
            socket_keepalive=True,
            decode_responses=True,
        )

    sentinels = parse_sentinels(os.getenv(REDIS_SENTINELS_ENV, ""))
    if not sentinels:
        raise QueueConfigurationError(
            f"Set ${REDIS_URL_ENV} or ${REDIS_SENTINELS_ENV} for durable webhook queues"
        )

    sentinel_password = os.getenv(REDIS_SENTINEL_PASSWORD_ENV, "").strip() or None
    redis_password = os.getenv(REDIS_PASSWORD_ENV, "").strip() or None
    sentinel_kwargs = {"password": sentinel_password} if sentinel_password else None
    sentinel = Sentinel(
        sentinels,
        socket_timeout=socket_timeout,
        sentinel_kwargs=sentinel_kwargs,
    )
    return sentinel.master_for(
        os.getenv(REDIS_SENTINEL_SERVICE_ENV, DEFAULT_REDIS_SENTINEL_SERVICE).strip()
        or DEFAULT_REDIS_SENTINEL_SERVICE,
        db=parse_int_env(REDIS_DB_ENV, DEFAULT_REDIS_DB),
        password=redis_password,
        socket_timeout=socket_timeout,
        socket_connect_timeout=socket_timeout,
        socket_keepalive=True,
        decode_responses=True,
    )


def job_dedupe_key(job: QueueJob) -> str:
    return job.delivery_id or job.event_id or job.submission_id


def serialize_job(job: QueueJob) -> str:
    return json.dumps(asdict(job), sort_keys=True, separators=(",", ":"))


class RedisReliableWebhookQueue[JobT]:
    def __init__(
        self,
        *,
        name: str,
        job_from_payload: Callable[[dict[str, Any]], JobT],
        process_job: Callable[[JobT], int],
        log_prefix: str,
        redis_client: Redis | None = None,
    ) -> None:
        self.name = name
        self.pending_key = f"wardn-hub:webhook:{name}:pending"
        self.processing_key = f"wardn-hub:webhook:{name}:processing"
        self.dedupe_key_prefix = f"wardn-hub:webhook:{name}:delivery:"
        self.job_from_payload = job_from_payload
        self.process_job = process_job
        self.log_prefix = log_prefix
        self.redis = redis_client or redis_client_from_env()
        self.dedupe_ttl_seconds = parse_int_env(
            REDIS_DEDUPE_TTL_ENV,
            DEFAULT_REDIS_DEDUPE_TTL_SECONDS,
        )
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self.redis.ping()
        self._reclaim_interrupted_jobs()
        self._stop.clear()
        self._worker = threading.Thread(
            target=self._run,
            name=f"wardn-{self.name}-redis-worker",
            daemon=True,
        )
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=5)

    def enqueue(self, job: JobT) -> bool:
        dedupe_value = job_dedupe_key(job)  # type: ignore[arg-type]
        dedupe_key = self.dedupe_key_prefix + dedupe_value
        inserted = self.redis.set(dedupe_key, "1", nx=True, ex=self.dedupe_ttl_seconds)
        if not inserted:
            metrics_service.record_webhook_enqueue(self.name, queued=False)
            return False
        payload = serialize_job(job)  # type: ignore[arg-type]
        try:
            self.redis.lpush(self.pending_key, payload)
        except Exception:
            self.redis.delete(dedupe_key)
            raise
        metrics_service.record_webhook_enqueue(self.name, queued=True)
        return True

    def queue_depths(self) -> list[metrics_service.QueueDepth]:
        return [
            metrics_service.QueueDepth(
                name=self.name,
                pending=int(self.redis.llen(self.pending_key)),
                processing=int(self.redis.llen(self.processing_key)),
            )
        ]

    def _run(self) -> None:
        while not self._stop.is_set():
            payload = self.redis.brpoplpush(
                self.pending_key,
                self.processing_key,
                timeout=1,
            )
            if payload is None:
                continue
            self._process_payload(str(payload))

    def _process_payload(self, payload: str) -> None:
        result = "success"
        try:
            job = self.job_from_payload(json.loads(payload))
            with metrics_service.webhook_job_timer(self.name):
                exit_code = self.process_job(job)
            if exit_code != 0:
                result = "nonzero"
                print(
                    f"{self.log_prefix}: job exited {exit_code}",
                    file=sys.stderr,
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001 - worker must keep consuming jobs.
            result = "failed"
            print(f"{self.log_prefix}: job failed: {exc}", file=sys.stderr, flush=True)
        finally:
            metrics_service.record_webhook_processed(self.name, result)
            self.redis.lrem(self.processing_key, 1, payload)

    def _reclaim_interrupted_jobs(self) -> None:
        while True:
            payload = self.redis.rpoplpush(self.processing_key, self.pending_key)
            if payload is None:
                return
