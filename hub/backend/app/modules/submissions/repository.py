import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.submissions.models import ServerSubmission


async def get_submission_by_id(
    session: AsyncSession,
    submission_id: uuid.UUID,
) -> ServerSubmission | None:
    return await session.get(ServerSubmission, submission_id)


async def list_submissions(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    include_all: bool = False,
) -> list[ServerSubmission]:
    statement = select(ServerSubmission).order_by(
        ServerSubmission.created_at.desc(),
        ServerSubmission.id.desc(),
    )
    if not include_all and user_id is not None:
        statement = statement.where(ServerSubmission.submitter_user_id == user_id)
    result = await session.execute(statement)
    return list(result.scalars().all())


async def delete_submission(
    session: AsyncSession,
    submission: ServerSubmission,
) -> None:
    await session.delete(submission)
