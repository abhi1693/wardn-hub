import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx

from app.modules.events import security
from app.modules.events.exceptions import EventValidationError
from app.modules.events.models import EventDelivery, EventRecord, EventRule

DEFAULT_RETRY_DELAYS_SECONDS = (30, 120, 300, 600, 1200, 1800)


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    response_status: int | None = None
    response_body: str = ""
    error_message: str = ""
    next_attempt_at: datetime | None = None


class EventActionHandler(Protocol):
    action_type: str

    async def deliver(
        self,
        *,
        event: EventRecord,
        rule: EventRule,
        delivery: EventDelivery,
    ) -> DeliveryResult:
        ...


def webhook_payload(event: EventRecord) -> dict[str, Any]:
    return event.payload


def webhook_headers(
    *,
    event_type: str,
    delivery_id: uuid.UUID,
    raw_body: bytes,
    signing_secret: str,
) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Wardn-Event": event_type,
        "Wardn-Delivery": str(delivery_id),
    }
    if signing_secret:
        timestamp = int(datetime.now(UTC).timestamp())
        headers["Wardn-Timestamp"] = str(timestamp)
        headers["Wardn-Signature"] = security.sign_webhook_payload(
            raw_body,
            signing_secret,
            timestamp=timestamp,
        )
    return headers


def next_retry_at(attempt_count: int) -> datetime | None:
    index = attempt_count - 1
    if index < 0 or index >= len(DEFAULT_RETRY_DELAYS_SECONDS):
        return None
    return datetime.now(UTC) + timedelta(seconds=DEFAULT_RETRY_DELAYS_SECONDS[index])


class WebhookActionHandler:
    action_type = "webhook"

    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def deliver(
        self,
        *,
        event: EventRecord,
        rule: EventRule,
        delivery: EventDelivery,
    ) -> DeliveryResult:
        url = str(rule.action_config.get("url") or "")
        try:
            security.validate_webhook_url(
                url,
                allow_private=rule.action_config.get("allowPrivateDestinations") is True,
            )
        except EventValidationError as exc:
            return DeliveryResult(status="failed", error_message=str(exc))
        signing_secret = str(rule.action_config.get("signingSecret") or "")
        raw_body = security.canonical_json_bytes(webhook_payload(event))
        headers = webhook_headers(
            event_type=event.event_type,
            delivery_id=delivery.id,
            raw_body=raw_body,
            signing_secret=signing_secret,
        )
        delivery.request_headers = {
            key: value for key, value in headers.items() if key != "Wardn-Signature"
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, content=raw_body, headers=headers)
        except httpx.HTTPError as exc:
            next_attempt = next_retry_at(delivery.attempt_count)
            return DeliveryResult(
                status="retrying" if next_attempt is not None else "failed",
                error_message=str(exc),
                next_attempt_at=next_attempt,
            )
        body = response.text
        if 200 <= response.status_code < 300:
            return DeliveryResult(
                status="succeeded",
                response_status=response.status_code,
                response_body=body,
            )
        next_attempt = next_retry_at(delivery.attempt_count)
        return DeliveryResult(
            status="retrying" if next_attempt is not None else "failed",
            response_status=response.status_code,
            response_body=body,
            error_message=f"webhook returned HTTP {response.status_code}",
            next_attempt_at=next_attempt,
        )


HANDLERS: dict[str, EventActionHandler] = {"webhook": WebhookActionHandler()}
