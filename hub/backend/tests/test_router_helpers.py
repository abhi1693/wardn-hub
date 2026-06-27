import pytest
from fastapi import status

from app.core.router import bad_request, commit_and_refresh, commit_response, not_found


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.refreshed: list[object] = []

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, record: object) -> None:
        self.refreshed.append(record)


def test_router_error_helpers_preserve_exception_details() -> None:
    error = not_found(ValueError("missing record"))

    assert error.status_code == status.HTTP_404_NOT_FOUND
    assert error.detail == "missing record"


def test_router_error_helpers_allow_route_specific_details() -> None:
    error = bad_request(ValueError("internal detail"), detail="invalid cursor")

    assert error.status_code == status.HTTP_400_BAD_REQUEST
    assert error.detail == "invalid cursor"


@pytest.mark.asyncio
async def test_commit_response_commits_and_returns_response() -> None:
    session = FakeSession()
    response = object()

    result = await commit_response(session, response)

    assert result is response
    assert session.commits == 1


@pytest.mark.asyncio
async def test_commit_and_refresh_commits_refreshes_and_returns_record() -> None:
    session = FakeSession()
    record = object()

    result = await commit_and_refresh(session, record)

    assert result is record
    assert session.commits == 1
    assert session.refreshed == [record]
