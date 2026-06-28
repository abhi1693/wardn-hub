from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, status

from app.cli import review_pending_submissions
from app.cli.webhook_queue import (
    QueueConfigurationError,
    RedisReliableWebhookQueue,
    WebhookQueue,
    durable_queue_requested,
)
from app.modules.events.security import verify_webhook_signature
from app.modules.metrics import service as metrics_service

WEBHOOK_SECRET_ENV = "WARDN_HUB_REVIEW_WEBHOOK_SECRET"
WEBHOOK_PATH_ENV = "WARDN_HUB_REVIEW_WEBHOOK_PATH"
WEBHOOK_HOST_ENV = "WARDN_HUB_REVIEW_WEBHOOK_HOST"
WEBHOOK_PORT_ENV = "WARDN_HUB_REVIEW_WEBHOOK_PORT"
DEFAULT_WEBHOOK_PATH = "/webhooks/wardn/submission-review"
DEFAULT_WEBHOOK_HOST = "0.0.0.0"
DEFAULT_WEBHOOK_PORT = 8090


class WebhookConfigurationError(Exception):
    pass


@dataclass(frozen=True)
class WebhookSettings:
    signing_secret: str
    api_base_url: str
    token: str
    review_command: str
    model: str
    thinking: str
    review_timeout: int
    http_timeout: int
    review_progress_interval: int
    verbose: bool


@dataclass(frozen=True)
class ReviewJob:
    submission_id: str
    delivery_id: str
    event_id: str


class SubmissionReviewQueue:
    def __init__(self, settings: WebhookSettings) -> None:
        self.settings = settings
        self._jobs: queue.Queue[ReviewJob | None] = queue.Queue()
        self._seen: set[str] = set()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._run, name="wardn-review-worker", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._jobs.put(None)
        if self._worker is not None:
            self._worker.join(timeout=5)

    def enqueue(self, job: ReviewJob) -> bool:
        dedupe_key = job.delivery_id or job.event_id or job.submission_id
        with self._lock:
            if dedupe_key in self._seen:
                metrics_service.record_webhook_enqueue("submission-review", queued=False)
                return False
            self._seen.add(dedupe_key)
        self._jobs.put(job)
        metrics_service.record_webhook_enqueue("submission-review", queued=True)
        return True

    def queue_depths(self) -> list[metrics_service.QueueDepth]:
        return [
            metrics_service.QueueDepth(
                name="submission-review",
                pending=self._jobs.qsize(),
                processing=0,
            )
        ]

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            result = "success"
            try:
                with metrics_service.webhook_job_timer("submission-review"):
                    exit_code = review_pending_submissions.main(
                        build_review_args(self.settings, job)
                    )
                if exit_code != 0:
                    result = "nonzero"
                    print(
                        f"review webhook: review job for {job.submission_id} exited {exit_code}",
                        file=sys.stderr,
                        flush=True,
                    )
            except Exception as exc:  # noqa: BLE001 - worker must keep consuming jobs.
                result = "failed"
                print(
                    f"review webhook: review job for {job.submission_id} failed: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
            finally:
                metrics_service.record_webhook_processed("submission-review", result)
                self._jobs.task_done()


def review_job_from_payload(payload: dict[str, Any]) -> ReviewJob:
    return ReviewJob(
        submission_id=str(payload.get("submission_id") or "").strip(),
        delivery_id=str(payload.get("delivery_id") or "").strip(),
        event_id=str(payload.get("event_id") or "").strip(),
    )


def build_review_queue(settings: WebhookSettings) -> WebhookQueue[ReviewJob]:
    if not durable_queue_requested():
        return SubmissionReviewQueue(settings)

    def process_job(job: ReviewJob) -> int:
        return review_pending_submissions.main(build_review_args(settings, job))

    return RedisReliableWebhookQueue(
        name="submission-review",
        job_from_payload=review_job_from_payload,
        process_job=process_job,
        log_prefix="review webhook",
    )


def build_review_args(settings: WebhookSettings, job: ReviewJob) -> list[str]:
    args = [
        "--url",
        settings.api_base_url,
        "--token",
        settings.token,
        "--review-command",
        settings.review_command,
        "--review-timeout",
        str(settings.review_timeout),
        "--review-progress-interval",
        str(settings.review_progress_interval),
        "--http-timeout",
        str(settings.http_timeout),
        "--submission-id",
        job.submission_id,
        "--once",
        "--non-interactive",
        "--auto-reject",
        "--auto-approve",
    ]
    if settings.model:
        args.extend(["--model", settings.model])
    if settings.thinking:
        args.extend(["--thinking", settings.thinking])
    if settings.verbose:
        args.append("--verbose")
    return args


def extract_submission_id(payload: dict[str, Any]) -> str:
    submission = payload.get("submission") if isinstance(payload.get("submission"), dict) else {}
    submission_id = submission.get("id") or payload.get("subject", {}).get("id")
    return str(submission_id or "").strip()


def verify_request_signature(raw_body: bytes, signature: str, settings: WebhookSettings) -> None:
    if not settings.signing_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="webhook signing secret is not configured",
        )
    if not signature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing signature")
    if not verify_webhook_signature(raw_body, settings.signing_secret, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid signature")


def create_app(
    settings: WebhookSettings,
    *,
    review_queue: WebhookQueue[ReviewJob] | None = None,
    start_worker: bool = True,
    path: str = DEFAULT_WEBHOOK_PATH,
) -> FastAPI:
    jobs = review_queue or build_review_queue(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if start_worker:
            jobs.start()
        try:
            yield
        finally:
            if start_worker:
                jobs.stop()

    app = FastAPI(title="Wardn submission review webhook", lifespan=lifespan)

    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def health_ready() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(
            content=metrics_service.process_metrics_text(
                metrics_service.queue_depth_metrics(jobs.queue_depths())
            ),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.post(path, status_code=status.HTTP_202_ACCEPTED)
    async def receive_submission_webhook(request: Request) -> dict[str, str | bool]:
        raw_body = await request.body()
        verify_request_signature(
            raw_body,
            request.headers.get("Wardn-Signature", ""),
            settings,
        )
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid payload")

        event_type = str(payload.get("eventType") or request.headers.get("Wardn-Event") or "")
        if event_type != "submission.submitted":
            return {"status": "ignored", "queued": False}

        submission_id = extract_submission_id(payload)
        if not submission_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="submission id is required",
            )

        job = ReviewJob(
            submission_id=submission_id,
            delivery_id=str(request.headers.get("Wardn-Delivery") or ""),
            event_id=str(payload.get("eventId") or ""),
        )
        queued = jobs.enqueue(job)
        return {"status": "queued" if queued else "duplicate", "queued": queued}

    return app


def int_from_env(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise WebhookConfigurationError(f"${name} must be an integer") from exc


def settings_from_env(args: argparse.Namespace) -> WebhookSettings:
    token = (args.token or os.getenv(review_pending_submissions.TOKEN_ENV, "")).strip()
    signing_secret = (args.signing_secret or os.getenv(WEBHOOK_SECRET_ENV, "")).strip()
    if not token:
        raise WebhookConfigurationError(
            "Missing Wardn Hub API token. Pass --token or set "
            f"{review_pending_submissions.TOKEN_ENV}."
        )
    if not signing_secret:
        raise WebhookConfigurationError(
            f"Missing webhook signing secret. Pass --signing-secret or set {WEBHOOK_SECRET_ENV}."
        )

    return WebhookSettings(
        signing_secret=signing_secret,
        api_base_url=args.api_base_url,
        token=token,
        review_command=args.review_command,
        model=args.model,
        thinking=args.thinking,
        review_timeout=args.review_timeout,
        http_timeout=args.http_timeout,
        review_progress_interval=args.review_progress_interval,
        verbose=args.verbose,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.review_submission_webhook",
        description=(
            "Receive Wardn submission.submitted webhooks and enqueue automated review jobs."
        ),
    )
    parser.add_argument(
        "--host",
        default=os.getenv(WEBHOOK_HOST_ENV, DEFAULT_WEBHOOK_HOST),
        help=f"Host to bind. Defaults to ${WEBHOOK_HOST_ENV} or {DEFAULT_WEBHOOK_HOST}.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Port to bind. Defaults to ${WEBHOOK_PORT_ENV} or {DEFAULT_WEBHOOK_PORT}.",
    )
    parser.add_argument(
        "--path",
        default=os.getenv(WEBHOOK_PATH_ENV, DEFAULT_WEBHOOK_PATH),
        help=f"Webhook path. Defaults to ${WEBHOOK_PATH_ENV} or {DEFAULT_WEBHOOK_PATH}.",
    )
    parser.add_argument(
        "--signing-secret",
        default="",
        help=f"Wardn event rule signing secret. Defaults to ${WEBHOOK_SECRET_ENV}.",
    )
    parser.add_argument(
        "--url",
        "--api-base-url",
        dest="api_base_url",
        default=os.getenv(
            review_pending_submissions.API_BASE_URL_ENV,
            review_pending_submissions.DEFAULT_API_BASE_URL,
        ),
        help=f"Wardn Hub API base URL. Defaults to ${review_pending_submissions.API_BASE_URL_ENV}.",
    )
    parser.add_argument(
        "--token",
        default="",
        help=f"Wardn Hub review API token. Defaults to ${review_pending_submissions.TOKEN_ENV}.",
    )
    parser.add_argument(
        "--review-command",
        default=os.getenv(
            review_pending_submissions.REVIEW_COMMAND_ENV,
            review_pending_submissions.DEFAULT_REVIEW_COMMAND,
        ),
        help=f"LLM review command. Defaults to ${review_pending_submissions.REVIEW_COMMAND_ENV}.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv(review_pending_submissions.REVIEW_MODEL_ENV, ""),
        help=(
            "Model to pass to Codex exec. Defaults to "
            f"${review_pending_submissions.REVIEW_MODEL_ENV}."
        ),
    )
    parser.add_argument(
        "--thinking",
        choices=review_pending_submissions.THINKING_LEVELS,
        default=os.getenv(review_pending_submissions.REVIEW_THINKING_ENV, ""),
        help=(
            "Thinking level to pass to Codex exec. Defaults to "
            f"${review_pending_submissions.REVIEW_THINKING_ENV}."
        ),
    )
    parser.add_argument(
        "--review-timeout",
        type=int,
        default=900,
        help="Seconds to wait for each LLM review command.",
    )
    parser.add_argument(
        "--review-progress-interval",
        type=int,
        default=int_from_env(review_pending_submissions.REVIEW_PROGRESS_INTERVAL_ENV, 15),
        help="Seconds between progress messages while the review command is silent.",
    )
    parser.add_argument(
        "--http-timeout",
        type=int,
        default=30,
        help="Seconds to wait for Wardn Hub API requests.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show live review command logs and progress status.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        if args.review_progress_interval < 0:
            raise WebhookConfigurationError("--review-progress-interval must be 0 or greater")
        settings = settings_from_env(args)
        app = create_app(settings, path=args.path)
        port = (
            args.port
            if args.port is not None
            else int_from_env(WEBHOOK_PORT_ENV, DEFAULT_WEBHOOK_PORT)
        )
        uvicorn.run(app, host=args.host, port=port)
        return 0
    except WebhookConfigurationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except QueueConfigurationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
