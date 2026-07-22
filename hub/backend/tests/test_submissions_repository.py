from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.submissions import repository


class EmptyScalarResult:
    def all(self) -> list[object]:
        return []

    def first(self) -> object | None:
        return None


class EmptyExecuteResult:
    def all(self) -> list[object]:
        return []

    def scalar_one(self) -> int:
        return 0

    def scalars(self) -> EmptyScalarResult:
        return EmptyScalarResult()


class StatusCountsExecuteResult(EmptyExecuteResult):
    def __init__(self, rows: list[tuple[str, int]]) -> None:
        self.rows = rows

    def all(self) -> list[tuple[str, int]]:
        return self.rows


class CaptureSession:
    def __init__(self, *, status_counts: list[tuple[str, int]] | None = None) -> None:
        self.statements: list[object] = []
        self.status_counts = status_counts or []

    async def execute(self, statement) -> EmptyExecuteResult:
        self.statements.append(statement)
        if len(self.statements) == 1:
            return StatusCountsExecuteResult(self.status_counts)
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

    statement = sql(session.statements[1])
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
    list_statement = sql(session.statements[1])

    for statement in (status_counts_statement, list_statement):
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
    list_statement = sql(session.statements[1])

    for statement in (status_counts_statement, list_statement):
        assert f"server_submissions.submitter_user_id = '{user_id}'" in statement
        assert f"server_submissions.owner_user_id = '{user_id}'" in statement


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_total"),
    [
        (None, 8),
        ("submitted", 5),
        ("approved", 0),
    ],
)
async def test_list_submissions_derives_total_from_status_counts(
    status: str | None,
    expected_total: int,
) -> None:
    session = CaptureSession(status_counts=[("draft", 3), ("submitted", 5)])

    _, total, status_counts = await repository.list_submissions(
        session,
        include_all=True,
        status=status,
    )

    assert total == expected_total
    assert status_counts == {"draft": 3, "submitted": 5}
    assert len(session.statements) == 2


@pytest.mark.asyncio
async def test_next_review_submission_fetches_only_one_eligible_row() -> None:
    skipped_id = uuid4()
    requested_id = uuid4()
    session = CaptureSession()

    submission = await repository.get_next_submitted_submission_for_review(
        session,
        exclude_ids={skipped_id},
        submission_id=requested_id,
    )

    statement = sql(session.statements[0])
    assert submission is None
    assert "server_submissions.status = 'submitted'" in statement
    assert f"server_submissions.id NOT IN ('{skipped_id}')" in statement
    assert f"server_submissions.id = '{requested_id}'" in statement
    assert "ORDER BY server_submissions.submitted_at ASC NULLS LAST" in statement
    assert "LIMIT 1" in statement


@pytest.mark.asyncio
async def test_next_system_fix_filters_owner_eligibility_in_database() -> None:
    session = CaptureSession()

    submission = await repository.get_next_repairable_submission_for_system_fix(
        session
    )

    statement = sql(session.statements[0])
    assert submission is None
    assert "server_submissions.status IN" in statement
    assert "'draft'" in statement
    assert "'rejected'" in statement
    assert "EXISTS (SELECT users.id" in statement
    assert "users.is_active IS true" in statement
    assert "users.is_superuser IS true" in statement
    assert "EXISTS (SELECT organizations.id" in statement
    assert "organizations.is_partner IS true" in statement
    assert "organizations.partner_status = 'active'" in statement
    assert "LIMIT 1" in statement
