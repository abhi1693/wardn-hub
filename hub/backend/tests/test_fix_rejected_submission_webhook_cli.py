from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from app.cli import fix_rejected_submission_webhook as webhook
from app.cli import fix_rejected_submissions
from app.modules.events import security


class CapturingQueue:
    def __init__(self) -> None:
        self.jobs: list[webhook.FixJob] = []

    def enqueue(self, job: webhook.FixJob) -> bool:
        if any(item.delivery_id == job.delivery_id for item in self.jobs):
            return False
        self.jobs.append(job)
        return True


def webhook_settings() -> webhook.WebhookSettings:
    return webhook.WebhookSettings(
        signing_secret="secret",
        api_base_url="https://hub.example.com/api/v1",
        token="wardn_hub_test_token",
        review_command="codex exec -",
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
    event_type: str = "submission.rejected",
    secret: str = "secret",
) -> tuple[bytes, dict[str, str]]:
    raw_body = security.canonical_json_bytes(payload)
    return raw_body, {
        "Content-Type": "application/json",
        "Wardn-Event": event_type,
        "Wardn-Delivery": "delivery-1",
        "Wardn-Signature": security.sign_webhook_payload(raw_body, secret),
    }


def test_build_fix_args_are_single_submission_only() -> None:
    settings = webhook_settings()
    job = webhook.FixJob(
        submission_id="sub-1",
        delivery_id="delivery-1",
        event_id="event-1",
    )

    args = webhook.build_fix_args(settings, job)

    assert args == [
        "--url",
        "https://hub.example.com/api/v1",
        "--token",
        "wardn_hub_test_token",
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
        "--model",
        "gpt-5",
        "--thinking",
        "high",
        "--verbose",
    ]
    assert "--max-fixes" not in args


def test_rejected_submission_webhook_verifies_signature_and_queues_submission() -> None:
    settings = webhook_settings()
    fix_queue = CapturingQueue()
    app = webhook.create_app(
        settings,
        fix_queue=fix_queue,  # type: ignore[arg-type]
        start_worker=False,
    )
    payload = {
        "eventId": "event-1",
        "eventType": "submission.rejected",
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
    assert fix_queue.jobs == [
        webhook.FixJob(submission_id="sub-1", delivery_id="delivery-1", event_id="event-1")
    ]


def test_rejected_submission_webhook_queues_draft_events() -> None:
    settings = webhook_settings()
    fix_queue = CapturingQueue()
    app = webhook.create_app(
        settings,
        fix_queue=fix_queue,  # type: ignore[arg-type]
        start_worker=False,
    )
    payload = {
        "eventId": "event-1",
        "eventType": "submission.created",
        "submission": {"id": "sub-1"},
    }
    raw_body, headers = signed_headers(payload, event_type="submission.created")

    response = TestClient(app).post(
        webhook.DEFAULT_WEBHOOK_PATH,
        content=raw_body,
        headers=headers,
    )

    assert response.status_code == 202
    assert response.json() == {"status": "queued", "queued": True}
    assert fix_queue.jobs == [
        webhook.FixJob(submission_id="sub-1", delivery_id="delivery-1", event_id="event-1")
    ]


def test_rejected_submission_webhook_ignores_other_event_types() -> None:
    settings = webhook_settings()
    fix_queue = CapturingQueue()
    app = webhook.create_app(
        settings,
        fix_queue=fix_queue,  # type: ignore[arg-type]
        start_worker=False,
    )
    payload = {
        "eventId": "event-1",
        "eventType": "submission.approved",
        "submission": {"id": "sub-1"},
    }
    raw_body, headers = signed_headers(payload, event_type="submission.approved")

    response = TestClient(app).post(
        webhook.DEFAULT_WEBHOOK_PATH,
        content=raw_body,
        headers=headers,
    )

    assert response.status_code == 202
    assert response.json() == {"status": "ignored", "queued": False}
    assert fix_queue.jobs == []


def test_rejected_submission_webhook_rejects_bad_signature() -> None:
    settings = webhook_settings()
    fix_queue = CapturingQueue()
    app = webhook.create_app(
        settings,
        fix_queue=fix_queue,  # type: ignore[arg-type]
        start_worker=False,
    )
    payload = {
        "eventId": "event-1",
        "eventType": "submission.rejected",
        "submission": {"id": "sub-1"},
    }
    raw_body = json.dumps(payload).encode("utf-8")

    response = TestClient(app).post(
        webhook.DEFAULT_WEBHOOK_PATH,
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "Wardn-Event": "submission.rejected",
            "Wardn-Delivery": "delivery-1",
            "Wardn-Signature": "t=1234,v1=bad",
        },
    )

    assert response.status_code == 401
    assert fix_queue.jobs == []


def test_rejected_submission_webhook_deduplicates_delivery() -> None:
    settings = webhook_settings()
    fix_queue = CapturingQueue()
    app = webhook.create_app(
        settings,
        fix_queue=fix_queue,  # type: ignore[arg-type]
        start_worker=False,
    )
    payload = {
        "eventId": "event-1",
        "eventType": "submission.rejected",
        "submission": {"id": "sub-1"},
    }
    raw_body, headers = signed_headers(payload)
    client = TestClient(app)

    first = client.post(webhook.DEFAULT_WEBHOOK_PATH, content=raw_body, headers=headers)
    second = client.post(webhook.DEFAULT_WEBHOOK_PATH, content=raw_body, headers=headers)

    assert first.json() == {"status": "queued", "queued": True}
    assert second.json() == {"status": "duplicate", "queued": False}
    assert len(fix_queue.jobs) == 1


def test_settings_from_env_requires_token_and_secret(monkeypatch) -> None:
    parser = webhook.build_parser()
    args = parser.parse_args([])
    monkeypatch.delenv(fix_rejected_submissions.TOKEN_ENV, raising=False)
    monkeypatch.delenv(webhook.WEBHOOK_SECRET_ENV, raising=False)

    try:
        webhook.settings_from_env(args)
    except webhook.WebhookConfigurationError as exc:
        assert "Missing Wardn Hub API token" in str(exc)
    else:
        raise AssertionError("expected WebhookConfigurationError")


def test_explicit_port_ignores_kubernetes_service_port_env(monkeypatch) -> None:
    monkeypatch.setenv(webhook.WEBHOOK_PORT_ENV, "tcp://10.43.16.137:8091")

    parser = webhook.build_parser()
    args = parser.parse_args(["--port", "8091"])

    assert args.port == 8091
