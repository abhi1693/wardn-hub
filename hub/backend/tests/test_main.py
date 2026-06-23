from fastapi.testclient import TestClient

from app.main import create_app


def test_app_metadata() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()

    assert schema["info"] == {
        "title": "Wardn Hub API",
        "version": "0.1.0",
    }


def test_unversioned_openapi_is_not_exposed() -> None:
    client = TestClient(create_app())

    assert client.get("/openapi.json").status_code == 404

