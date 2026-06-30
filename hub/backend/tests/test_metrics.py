from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app
from app.modules.metrics import service


def teardown_function() -> None:
    service.clear_registry_metrics_cache()


def test_metrics_endpoint_exposes_process_and_database_metrics(monkeypatch) -> None:
    async def fake_session() -> AsyncIterator[object]:
        yield object()

    async def collect_database_metrics(_session: object) -> str:
        return "# HELP wardn_submissions_total test\nwardn_submissions_total 2\n"

    monkeypatch.setattr(service, "collect_database_metrics", collect_database_metrics)

    app = create_app()
    app.dependency_overrides[get_db_session] = fake_session
    client = TestClient(app)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "wardn_webhook_jobs_enqueued_total" in response.text
    assert "wardn_submissions_total 2" in response.text


def test_metrics_endpoint_is_not_in_openapi() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()

    assert "/metrics" not in schema["paths"]


async def test_cached_registry_metrics_reuses_lines_within_ttl(monkeypatch) -> None:
    calls = 0
    current_time = 100.0

    async def registry_metrics(_session: object) -> list[str]:
        nonlocal calls
        calls += 1
        return [f"registry_metric {calls}"]

    def now() -> float:
        return current_time

    monkeypatch.setenv(service.REGISTRY_METRICS_CACHE_TTL_ENV, "60")
    monkeypatch.setattr(service, "registry_metrics", registry_metrics)

    first = await service.cached_registry_metrics(object(), now=now)
    second = await service.cached_registry_metrics(object(), now=now)

    assert first == ["registry_metric 1"]
    assert second == first
    assert calls == 1


async def test_cached_registry_metrics_refreshes_after_ttl(monkeypatch) -> None:
    calls = 0
    current_time = 100.0

    async def registry_metrics(_session: object) -> list[str]:
        nonlocal calls
        calls += 1
        return [f"registry_metric {calls}"]

    def now() -> float:
        return current_time

    monkeypatch.setenv(service.REGISTRY_METRICS_CACHE_TTL_ENV, "60")
    monkeypatch.setattr(service, "registry_metrics", registry_metrics)

    first = await service.cached_registry_metrics(object(), now=now)
    current_time = 161.0
    second = await service.cached_registry_metrics(object(), now=now)

    assert first == ["registry_metric 1"]
    assert second == ["registry_metric 2"]
    assert calls == 2


async def test_cached_registry_metrics_can_be_disabled(monkeypatch) -> None:
    calls = 0

    async def registry_metrics(_session: object) -> list[str]:
        nonlocal calls
        calls += 1
        return [f"registry_metric {calls}"]

    monkeypatch.setenv(service.REGISTRY_METRICS_CACHE_TTL_ENV, "0")
    monkeypatch.setattr(service, "registry_metrics", registry_metrics)

    first = await service.cached_registry_metrics(object())
    second = await service.cached_registry_metrics(object())

    assert first == ["registry_metric 1"]
    assert second == ["registry_metric 2"]
    assert calls == 2
