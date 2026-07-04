import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organizations.models import OrganizationMembership
from app.modules.submissions.models import ServerSubmission


def submission_search_filter(search: str | None) -> object | None:
    if not search:
        return None

    pattern = f"%{search}%"
    return or_(
        ServerSubmission.name.ilike(pattern),
        ServerSubmission.version.ilike(pattern),
        ServerSubmission.submission_type.ilike(pattern),
        ServerSubmission.status.ilike(pattern),
        ServerSubmission.rejection_message.ilike(pattern),
        ServerSubmission.server_json["title"].as_string().ilike(pattern),
        ServerSubmission.server_json["description"].as_string().ilike(pattern),
        ServerSubmission.server_json["repository"]["url"].as_string().ilike(pattern),
        ServerSubmission.server_json["websiteUrl"].as_string().ilike(pattern),
    )


def submission_visibility_filters(
    *,
    user_id: uuid.UUID | None,
    include_all: bool,
    organization_ids: set[str] | None = None,
) -> list[object]:
    filters: list[object] = []
    if not include_all and user_id is not None:
        user_organization_ids = select(OrganizationMembership.organization_id).where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.is_active.is_(True),
        )
        filters.append(
            or_(
                ServerSubmission.submitter_user_id == user_id,
                ServerSubmission.owner_organization_id.in_(user_organization_ids),
            )
        )
    if organization_ids:
        filters.append(
            ServerSubmission.owner_organization_id.in_(
                [uuid.UUID(str(organization_id)) for organization_id in organization_ids]
            )
        )
    return filters


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
    organization_ids: set[str] | None = None,
    status: str | None = None,
    search: str | None = None,
    filter_user_id: uuid.UUID | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[ServerSubmission], int, dict[str, int]]:
    base_filters = submission_visibility_filters(
        user_id=user_id,
        include_all=include_all,
        organization_ids=organization_ids,
    )
    search_filter = submission_search_filter(search)
    count_filters = [*base_filters]
    if search_filter is not None:
        count_filters.append(search_filter)
    if filter_user_id is not None:
        count_filters.append(
            or_(
                ServerSubmission.submitter_user_id == filter_user_id,
                ServerSubmission.owner_user_id == filter_user_id,
            )
        )

    status_counts_result = await session.execute(
        select(ServerSubmission.status, func.count())
        .where(*count_filters)
        .group_by(ServerSubmission.status)
    )
    status_counts = {
        str(status_name): count for status_name, count in status_counts_result.all()
    }

    filters = [*count_filters]
    if status is not None:
        filters.append(ServerSubmission.status == status)

    total_result = await session.execute(
        select(func.count()).select_from(ServerSubmission).where(*filters)
    )
    total = int(total_result.scalar_one())

    statement = select(ServerSubmission).order_by(
        ServerSubmission.updated_at.desc(),
        ServerSubmission.id.desc(),
    )
    if filters:
        statement = statement.where(*filters)
    result = await session.execute(statement.offset(offset).limit(limit))
    return list(result.scalars().all()), total, status_counts


async def list_submitted_submissions_for_review(
    session: AsyncSession,
) -> list[ServerSubmission]:
    statement = (
        select(ServerSubmission)
        .where(ServerSubmission.status == "submitted")
        .order_by(
            ServerSubmission.submitted_at.asc().nullslast(),
            ServerSubmission.created_at.asc(),
            ServerSubmission.id.asc(),
        )
    )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def list_repairable_submissions_for_system_fix(
    session: AsyncSession,
) -> list[ServerSubmission]:
    statement = (
        select(ServerSubmission)
        .where(ServerSubmission.status.in_({"draft", "rejected"}))
        .order_by(
            ServerSubmission.updated_at.asc().nullslast(),
            ServerSubmission.created_at.asc(),
            ServerSubmission.id.asc(),
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
