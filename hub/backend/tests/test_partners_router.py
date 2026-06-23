from fastapi.testclient import TestClient

from app.main import create_app


def test_partner_list_requires_authentication() -> None:
    response = TestClient(create_app()).get("/api/v1/partners")

    assert response.status_code == 401


def test_partner_update_requires_authentication() -> None:
    response = TestClient(create_app()).patch(
        "/api/v1/partners/organizations/00000000-0000-0000-0000-000000000000",
        json={"isPartner": True},
    )

    assert response.status_code == 401
