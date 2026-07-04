from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.submissions import repository


class EmptyScalarResult:
    def all(self) -> list[object]:
        return []


class EmptyExecuteResult:
    def all(self) -> list[object]:
        return []

    def scalar_one(self) -> int:
        return 0

    def scalars(self) -> EmptyScalarResult:
        return EmptyScalarResult()


class CaptureSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement) -> EmptyExecuteResult:
        self.statements.append(statement)
        return EmptyExecuteResult()


def sql(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


@pytest.mark.asyncio
async def test_list_submissions_includes_owned_organization_memberships() -> None:
    user_id = uuid4()
    session = CaptureSession()

    submissions, total, status_counts = await repository.list_submissions(
        session,
        user_id=user_id,
        include_all=False,
    )

    statement = sql(session.statements[2])
    assert submissions == []
    assert total == 0
    assert status_counts == {}
    assert f"server_submissions.submitter_user_id = '{user_id}'" in statement
    assert "server_submissions.owner_organization_id IN" in statement
    assert "organization_memberships.organization_id" in statement
    assert f"organization_memberships.user_id = '{user_id}'" in statement
    assert "organization_memberships.is_active IS true" in statement


@pytest.mark.asyncio
async def test_list_submissions_applies_search_to_status_counts_and_results() -> None:
    session = CaptureSession()

    await repository.list_submissions(
        session,
        include_all=True,
        search="weather",
    )

    status_counts_statement = sql(session.statements[0])
    total_statement = sql(session.statements[1])
    list_statement = sql(session.statements[2])

    for statement in (status_counts_statement, total_statement, list_statement):
        assert "server_submissions.name ILIKE '%%weather%%'" in statement
        assert "server_submissions.version ILIKE '%%weather%%'" in statement
        assert "server_submissions.server_json ->> 'title'" in statement
        assert "server_submissions.server_json ->> 'description'" in statement


@pytest.mark.asyncio
async def test_list_submissions_applies_user_filter_to_status_counts_and_results() -> None:
    user_id = uuid4()
    session = CaptureSession()

    await repository.list_submissions(
        session,
        include_all=True,
        filter_user_id=user_id,
    )

    status_counts_statement = sql(session.statements[0])
    total_statement = sql(session.statements[1])
    list_statement = sql(session.statements[2])

    for statement in (status_counts_statement, total_statement, list_statement):
        assert f"server_submissions.submitter_user_id = '{user_id}'" in statement
        assert f"server_submissions.owner_user_id = '{user_id}'" in statement
