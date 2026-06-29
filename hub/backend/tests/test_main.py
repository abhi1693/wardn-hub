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


def test_openapi_docs_ui_is_exposed() -> None:
    client = TestClient(create_app())

    swagger = client.get("/api/v1/docs")
    redoc = client.get("/api/v1/redoc")

    assert swagger.status_code == 200
    assert swagger.headers["content-type"].startswith("text/html")
    assert "/api/v1/openapi.json" in swagger.text
    assert redoc.status_code == 200
    assert redoc.headers["content-type"].startswith("text/html")
    assert "/api/v1/openapi.json" in redoc.text


def test_root_docs_routes_redirect_to_versioned_docs_ui() -> None:
    client = TestClient(create_app(), follow_redirects=False)

    docs = client.get("/docs")
    redoc = client.get("/redoc")

    assert docs.status_code == 307
    assert docs.headers["location"] == "/api/v1/docs"
    assert redoc.status_code == 307
    assert redoc.headers["location"] == "/api/v1/redoc"
