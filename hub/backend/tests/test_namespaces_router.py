from fastapi.testclient import TestClient

from app.main import create_app


def test_namespace_claim_routes_are_disabled() -> None:
    response = TestClient(create_app()).get("/api/v1/namespaces/claims")

    assert response.status_code == 404


def test_namespace_claim_create_route_is_disabled() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/namespaces/claims",
        json={"namespace": "io.github.example/*"},
    )

    assert response.status_code == 404
