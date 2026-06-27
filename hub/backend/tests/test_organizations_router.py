from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app
from app.modules.organizations import router
from app.modules.users.dependencies import get_current_user
from app.modules.users.exceptions import UserNotFoundError


def test_membership_upsert_maps_missing_user_to_not_found(monkeypatch) -> None:
    app = create_app()

    async def fake_session():
        class Session:
            async def commit(self) -> None:
                raise AssertionError("commit should not be called")

        yield Session()

    async def current_user():
        return SimpleNamespace(id=uuid4(), is_active=True)

    async def missing_user(*args, **kwargs):
        raise UserNotFoundError("user not found")

    app.dependency_overrides[get_db_session] = fake_session
    app.dependency_overrides[get_current_user] = current_user
    monkeypatch.setattr(router, "upsert_membership", missing_user)

    response = TestClient(app).post(
        f"/api/v1/organizations/{uuid4()}/memberships",
        json={"userId": str(uuid4()), "roleSlug": "member"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "user not found"}
