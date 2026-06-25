from fastapi.testclient import TestClient

from app.core.config import APP_VERSION
from app.main import create_app


def test_app_metadata() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()

    assert schema["info"] == {
        "title": "Wardn Hub API",
        "version": APP_VERSION,
    }


def test_unversioned_openapi_is_not_exposed() -> None:
    client = TestClient(create_app())

    assert client.get("/openapi.json").status_code == 404
