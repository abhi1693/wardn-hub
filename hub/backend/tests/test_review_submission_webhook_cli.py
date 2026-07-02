from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from fastapi.testclient import TestClient

from app.cli import review_pending_submissions
from app.cli import review_submission_webhook as webhook
from app.modules.events import security


class CapturingQueue:
    def __init__(self) -> None:
        self.jobs: list[webhook.ReviewJob] = []

    def enqueue(self, job: webhook.ReviewJob) -> bool:
        if any(item.delivery_id == job.delivery_id for item in self.jobs):
            return False
        self.jobs.append(job)
        return True


def webhook_settings() -> webhook.WebhookSettings:
    return webhook.WebhookSettings(
        signing_secret="secret",
        api_base_url="https://hub.example.com/api/v1",
        system_review_secret="system-review-secret",
        review_command="codex exec -",
        codex_app_server_url="",
        model="gpt-5",
        thinking="high",
        review_timeout=123,
        http_timeout=12,
        review_progress_interval=3,
        verbose=True,
    )


def signed_headers(
    payload: dict[str, Any],
    *,
    secret: str = "secret",
) -> tuple[bytes, dict[str, str]]:
    raw_body = security.canonical_json_bytes(payload)
    return raw_body, {
        "Content-Type": "application/json",
        "Wardn-Event": "submission.submitted",
        "Wardn-Delivery": "delivery-1",
        "Wardn-Signature": security.sign_webhook_payload(raw_body, secret),
    }


def test_build_review_args_are_webhook_safe() -> None:
    settings = webhook_settings()
    job = webhook.ReviewJob(
        submission_id="sub-1",
        delivery_id="delivery-1",
        event_id="event-1",
    )

    args = webhook.build_review_args(settings, job)

    assert args == [
        "--url",
        "https://hub.example.com/api/v1",
        "--system-review-secret",
        "system-review-secret",
        "--review-command",
        "codex exec -",
        "--review-timeout",
        "123",
        "--review-progress-interval",
        "3",
        "--http-timeout",
        "12",
        "--submission-id",
        "sub-1",
        "--once",
        "--non-interactive",
        "--auto-reject",
        "--auto-approve",
        "--model",
        "gpt-5",
        "--thinking",
        "high",
        "--verbose",
    ]


def test_build_review_args_can_auto_publish() -> None:
    settings = replace(webhook_settings(), auto_publish=True)
    job = webhook.ReviewJob(
        submission_id="sub-1",
        delivery_id="delivery-1",
        event_id="event-1",
    )

    args = webhook.build_review_args(settings, job)

    assert "--auto-publish" in args
    assert "--auto-approve" not in args


def test_build_review_args_can_use_codex_app_server() -> None:
    settings = replace(webhook_settings(), codex_app_server_url="ws://127.0.0.1:41237")
    job = webhook.ReviewJob(
        submission_id="sub-1",
        delivery_id="delivery-1",
        event_id="event-1",
    )

    args = webhook.build_review_args(settings, job)

    assert "--codex-app-server-url" in args
    assert args[args.index("--codex-app-server-url") + 1] == "ws://127.0.0.1:41237"


def test_auto_publish_argument_is_disabled_by_default() -> None:
    parser = webhook.build_parser()
    default_args = parser.parse_args([])
    auto_publish_args = parser.parse_args(["--auto-publish"])

    assert default_args.auto_publish is False
    assert auto_publish_args.auto_publish is True


def test_submission_webhook_verifies_signature_and_queues_submission() -> None:
    settings = webhook_settings()
    review_queue = CapturingQueue()
    app = webhook.create_app(
        settings,
        review_queue=review_queue,  # type: ignore[arg-type]
        start_worker=False,
    )
    payload = {
        "eventId": "event-1",
        "eventType": "submission.submitted",
        "submission": {"id": "sub-1"},
    }
    raw_body, headers = signed_headers(payload)

    response = TestClient(app).post(
        webhook.DEFAULT_WEBHOOK_PATH,
        content=raw_body,
        headers=headers,
    )

    assert response.status_code == 202
    assert response.json() == {"status": "queued", "queued": True}
    assert review_queue.jobs == [
        webhook.ReviewJob(submission_id="sub-1", delivery_id="delivery-1", event_id="event-1")
    ]


def test_health_endpoints_do_not_require_signature() -> None:
    app = webhook.create_app(webhook_settings(), start_worker=False)
    client = TestClient(app)

    live = client.get("/health/live")
    ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ok"}


def test_submission_webhook_rejects_bad_signature() -> None:
    settings = webhook_settings()
    review_queue = CapturingQueue()
    app = webhook.create_app(
        settings,
        review_queue=review_queue,  # type: ignore[arg-type]
        start_worker=False,
    )
    payload = {
        "eventId": "event-1",
        "eventType": "submission.submitted",
        "submission": {"id": "sub-1"},
    }
    raw_body = json.dumps(payload).encode("utf-8")

    response = TestClient(app).post(
        webhook.DEFAULT_WEBHOOK_PATH,
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "Wardn-Event": "submission.submitted",
            "Wardn-Delivery": "delivery-1",
            "Wardn-Signature": "t=1234,v1=bad",
        },
    )

    assert response.status_code == 401
    assert review_queue.jobs == []


def test_submission_webhook_deduplicates_delivery() -> None:
    settings = webhook_settings()
    review_queue = CapturingQueue()
    app = webhook.create_app(
        settings,
        review_queue=review_queue,  # type: ignore[arg-type]
        start_worker=False,
    )
    payload = {
        "eventId": "event-1",
        "eventType": "submission.submitted",
        "submission": {"id": "sub-1"},
    }
    raw_body, headers = signed_headers(payload)
    client = TestClient(app)

    first = client.post(webhook.DEFAULT_WEBHOOK_PATH, content=raw_body, headers=headers)
    second = client.post(webhook.DEFAULT_WEBHOOK_PATH, content=raw_body, headers=headers)

    assert first.json() == {"status": "queued", "queued": True}
    assert second.json() == {"status": "duplicate", "queued": False}
    assert len(review_queue.jobs) == 1


def test_settings_from_env_requires_system_review_secret_and_webhook_secret(monkeypatch) -> None:
    parser = webhook.build_parser()
    args = parser.parse_args([])
    monkeypatch.delenv(review_pending_submissions.TOKEN_ENV, raising=False)
    monkeypatch.delenv(review_pending_submissions.SYSTEM_REVIEW_SECRET_ENV, raising=False)
    monkeypatch.delenv(webhook.WEBHOOK_SECRET_ENV, raising=False)

    try:
        webhook.settings_from_env(args)
    except webhook.WebhookConfigurationError as exc:
        assert "Missing Wardn Hub system review secret" in str(exc)
    else:
        raise AssertionError("expected WebhookConfigurationError")


def test_explicit_port_ignores_kubernetes_service_port_env(monkeypatch) -> None:
    monkeypatch.setenv(webhook.WEBHOOK_PORT_ENV, "tcp://10.43.16.137:8090")

    parser = webhook.build_parser()
    args = parser.parse_args(["--port", "8090"])

    assert args.port == 8090
