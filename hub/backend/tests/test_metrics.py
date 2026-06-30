from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app
from app.modules.metrics import service


def test_metrics_endpoint_exposes_process_and_database_metrics(monkeypatch) -> None:
    async def fake_session() -> AsyncIterator[object]:
        yield object()

    async def collect_database_metrics(_session: object) -> str:
        return (
            "# HELP wardn_submission_review_backlog_total test\n"
            "wardn_submission_review_backlog_total 2\n"
        )

    monkeypatch.setattr(service, "collect_database_metrics", collect_database_metrics)

    app = create_app()
    app.dependency_overrides[get_db_session] = fake_session
    client = TestClient(app)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "wardn_webhook_jobs_enqueued_total" in response.text
    assert "wardn_submission_review_backlog_total 2" in response.text


def test_metrics_endpoint_is_not_in_openapi() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()

    assert "/metrics" not in schema["paths"]
