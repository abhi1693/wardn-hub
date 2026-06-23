from fastapi.testclient import TestClient

from app.main import create_app


def test_namespace_claims_require_authentication() -> None:
    response = TestClient(create_app()).get("/api/v1/namespaces/claims")

    assert response.status_code == 401


def test_namespace_claim_create_requires_authentication() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/namespaces/claims",
        json={"namespace": "io.github.example/*"},
    )

    assert response.status_code == 401
