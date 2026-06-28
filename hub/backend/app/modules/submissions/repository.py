import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organizations.models import OrganizationMembership
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
        organization_ids = select(OrganizationMembership.organization_id).where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.is_active.is_(True),
        )
        statement = statement.where(
            or_(
                ServerSubmission.submitter_user_id == user_id,
                ServerSubmission.owner_organization_id.in_(organization_ids),
            )
        )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def get_submission_by_name_version(
    session: AsyncSession,
    *,
    name: str,
    version: str,
    statuses: set[str],
    exclude_id: uuid.UUID | None = None,
) -> ServerSubmission | None:
    statement = select(ServerSubmission).where(
        ServerSubmission.name == name,
        ServerSubmission.version == version,
        ServerSubmission.status.in_(statuses),
    )
    if exclude_id is not None:
        statement = statement.where(ServerSubmission.id != exclude_id)
    statement = statement.order_by(
        ServerSubmission.updated_at.desc().nullslast(),
        ServerSubmission.created_at.desc().nullslast(),
        ServerSubmission.id.desc(),
    )
    result = await session.execute(statement)
    return result.scalars().first()


async def delete_submission(
    session: AsyncSession,
    submission: ServerSubmission,
) -> None:
    await session.delete(submission)
