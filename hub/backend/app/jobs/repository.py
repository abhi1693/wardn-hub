from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import String, and_, cast, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.models import ScheduledJobState, WorkerItemState
from app.modules.organizations.models import Organization
from app.modules.skills.models import Skill, SkillAudit, SkillSnapshot
from app.modules.submissions.models import ServerSubmission
from app.modules.users.models import User


@dataclass(frozen=True)
class ClaimedWorkItem:
    item_id: str
    command_id: str
    claim_token: uuid.UUID
    item_revision: str | None
    item_updated_at: datetime | None
    attempt_count: int


def utc_now() -> datetime:
    return datetime.now(UTC)


def error_retry_delay(
    item: ClaimedWorkItem,
    *,
    initial_retry_seconds: float,
    maximum_retry_seconds: float,
) -> float:
    exponent = min(max(item.attempt_count - 1, 0), 31)
    return min(
        maximum_retry_seconds,
        initial_retry_seconds * (2**exponent),
    )


def unavailable_item_state(
    *,
    job_name: str,
    item_id: object,
    now: datetime,
    item_revision: object | None = None,
    item_updated_at: object | None = None,
) -> object:
    matching_input = [
        WorkerItemState.job_name == job_name,
        WorkerItemState.item_id == item_id,
    ]
    if item_revision is not None:
        matching_input.append(WorkerItemState.item_revision == item_revision)
    if item_updated_at is not None:
        matching_input.append(WorkerItemState.item_updated_at == item_updated_at)
    return exists(
        select(WorkerItemState.job_name).where(
            *matching_input,
            or_(
                WorkerItemState.claimed_until > now,
                WorkerItemState.retry_after > now,
            ),
        )
    )


async def claim_item_state(
    session: AsyncSession,
    *,
    job_name: str,
    item_id: str,
    command_id: str,
    lease_seconds: float,
    item_revision: str | None = None,
    item_updated_at: datetime | None = None,
    now: datetime | None = None,
) -> ClaimedWorkItem:
    claimed_at = now or utc_now()
    claim_token = uuid.uuid4()
    state = await session.get(WorkerItemState, (job_name, item_id))
    same_input = (
        state is not None
        and state.item_revision == item_revision
        and state.item_updated_at == item_updated_at
    )
    if state is None:
        state = WorkerItemState(
            job_name=job_name,
            item_id=item_id,
            claim_token=claim_token,
            item_revision=item_revision,
            item_updated_at=item_updated_at,
            attempt_count=1,
        )
        session.add(state)
    else:
        state.claim_token = claim_token
        state.item_revision = item_revision
        state.item_updated_at = item_updated_at
        state.attempt_count = state.attempt_count + 1 if same_input else 1
    state.claimed_until = claimed_at + timedelta(seconds=lease_seconds)
    state.retry_after = None
    state.last_result = "claimed"
    state.last_error = ""
    await session.flush()
    return ClaimedWorkItem(
        item_id=item_id,
        command_id=command_id,
        claim_token=claim_token,
        item_revision=item_revision,
        item_updated_at=item_updated_at,
        attempt_count=state.attempt_count,
    )


async def claim_next_submission_review(
    session: AsyncSession,
    *,
    lease_seconds: float,
    now: datetime | None = None,
) -> ClaimedWorkItem | None:
    claimed_at = now or utc_now()
    statement = (
        select(ServerSubmission)
        .where(
            ServerSubmission.status == "submitted",
            ~unavailable_item_state(
                job_name="submission-review",
                item_id=cast(ServerSubmission.id, String(256)),
                item_updated_at=ServerSubmission.updated_at,
                now=claimed_at,
            ),
        )
        .order_by(
            ServerSubmission.submitted_at.asc().nullslast(),
            ServerSubmission.created_at.asc(),
            ServerSubmission.id.asc(),
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    submission = (await session.execute(statement)).scalars().first()
    if submission is None:
        return None
    return await claim_item_state(
        session,
        job_name="submission-review",
        item_id=str(submission.id),
        command_id=str(submission.id),
        item_updated_at=submission.updated_at,
        lease_seconds=lease_seconds,
        now=claimed_at,
    )


async def claim_next_submission_repair(
    session: AsyncSession,
    *,
    lease_seconds: float,
    now: datetime | None = None,
) -> ClaimedWorkItem | None:
    claimed_at = now or utc_now()
    eligible_user_owner = exists(
        select(User.id).where(
            User.id == ServerSubmission.owner_user_id,
            User.is_active.is_(True),
            User.is_superuser.is_(True),
        )
    )
    eligible_organization_owner = exists(
        select(Organization.id).where(
            Organization.id == ServerSubmission.owner_organization_id,
            Organization.status == "active",
            Organization.is_partner.is_(True),
            Organization.partner_status == "active",
        )
    )
    statement = (
        select(ServerSubmission)
        .where(
            ServerSubmission.status.in_(("draft", "rejected")),
            or_(eligible_user_owner, eligible_organization_owner),
            ~unavailable_item_state(
                job_name="submission-repair",
                item_id=cast(ServerSubmission.id, String(256)),
                item_updated_at=ServerSubmission.updated_at,
                now=claimed_at,
            ),
        )
        .order_by(
            ServerSubmission.updated_at.asc().nullslast(),
            ServerSubmission.created_at.asc(),
            ServerSubmission.id.asc(),
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    submission = (await session.execute(statement)).scalars().first()
    if submission is None:
        return None
    return await claim_item_state(
        session,
        job_name="submission-repair",
        item_id=str(submission.id),
        command_id=str(submission.id),
        item_updated_at=submission.updated_at,
        lease_seconds=lease_seconds,
        now=claimed_at,
    )


def completed_skill_audit(
    *,
    skill_id: object,
    snapshot_id: object,
    content_hash: object,
) -> object:
    return exists(
        select(SkillAudit.id).where(
            SkillAudit.skill_id == skill_id,
            SkillAudit.snapshot_id == snapshot_id,
            SkillAudit.content_hash == content_hash,
            SkillAudit.status.in_(("pass", "warn", "fail")),
        )
    )


async def claim_next_skill_audit(
    session: AsyncSession,
    *,
    lease_seconds: float,
    published_before: datetime,
    now: datetime | None = None,
) -> ClaimedWorkItem | None:
    claimed_at = now or utc_now()
    statement = (
        select(Skill, SkillSnapshot)
        .join(
            SkillSnapshot,
            and_(
                SkillSnapshot.id == Skill.current_snapshot_id,
                SkillSnapshot.skill_id == Skill.id,
            ),
        )
        .where(
            Skill.status == "active",
            Skill.visibility == "public",
            Skill.current_snapshot_id.is_not(None),
            SkillSnapshot.status == "active",
            SkillSnapshot.is_latest.is_(True),
            SkillSnapshot.content_hash.is_not(None),
            SkillSnapshot.bundle_format_version == 2,
            SkillSnapshot.resolution_status == "complete",
            SkillSnapshot.published_at <= published_before,
            ~completed_skill_audit(
                skill_id=Skill.id,
                snapshot_id=SkillSnapshot.id,
                content_hash=SkillSnapshot.content_hash,
            ),
            ~unavailable_item_state(
                job_name="skill-maintenance",
                item_id=cast(Skill.id, String(256)),
                item_revision=SkillSnapshot.content_hash,
                now=claimed_at,
            ),
        )
        .order_by(
            SkillSnapshot.published_at.asc(),
            Skill.id.asc(),
        )
        .with_for_update(skip_locked=True, of=Skill)
        .limit(1)
    )
    row = (await session.execute(statement)).first()
    if row is None:
        return None
    skill, snapshot = row
    return await claim_item_state(
        session,
        job_name="skill-maintenance",
        item_id=str(skill.id),
        command_id=f"{skill.source}/{skill.slug}",
        item_revision=snapshot.content_hash,
        lease_seconds=lease_seconds,
        now=claimed_at,
    )


async def defer_item_state(
    session: AsyncSession,
    item: ClaimedWorkItem,
    *,
    job_name: str,
    retry_seconds: float,
    result: str,
    error: str = "",
    now: datetime | None = None,
) -> bool:
    finished_at = now or utc_now()
    update_result = await session.execute(
        update(WorkerItemState)
        .where(
            WorkerItemState.job_name == job_name,
            WorkerItemState.item_id == item.item_id,
            WorkerItemState.claim_token == item.claim_token,
            WorkerItemState.item_revision.is_not_distinct_from(item.item_revision),
            WorkerItemState.item_updated_at.is_not_distinct_from(item.item_updated_at),
        )
        .values(
            claimed_until=None,
            retry_after=finished_at + timedelta(seconds=retry_seconds),
            last_result=result[:32],
            last_error=error[:10_000],
        )
        .execution_options(synchronize_session=False)
    )
    return update_result.rowcount == 1


async def delete_item_state(
    session: AsyncSession,
    item: ClaimedWorkItem,
    *,
    job_name: str,
) -> bool:
    delete_result = await session.execute(
        delete(WorkerItemState)
        .where(
            WorkerItemState.job_name == job_name,
            WorkerItemState.item_id == item.item_id,
            WorkerItemState.claim_token == item.claim_token,
            WorkerItemState.item_revision.is_not_distinct_from(item.item_revision),
            WorkerItemState.item_updated_at.is_not_distinct_from(item.item_updated_at),
        )
        .execution_options(synchronize_session=False)
    )
    return delete_result.rowcount == 1


async def finish_submission_item(
    session: AsyncSession,
    item: ClaimedWorkItem,
    *,
    job_name: str,
    eligible_statuses: tuple[str, ...],
    return_code: int,
    deferred_retry_seconds: float,
    error_retry_seconds: float,
    now: datetime | None = None,
) -> str:
    submission = await session.get(ServerSubmission, uuid.UUID(item.item_id))
    if (
        submission is None
        or submission.status not in eligible_statuses
        or submission.updated_at != item.item_updated_at
    ):
        deleted = await delete_item_state(session, item, job_name=job_name)
        return "completed" if deleted else "stale"
    result = "deferred" if return_code == 0 else "error"
    retry_seconds = (
        deferred_retry_seconds
        if return_code == 0
        else error_retry_delay(
            item,
            initial_retry_seconds=error_retry_seconds,
            maximum_retry_seconds=deferred_retry_seconds,
        )
    )
    deferred = await defer_item_state(
        session,
        item,
        job_name=job_name,
        retry_seconds=retry_seconds,
        result=result,
        error="" if return_code == 0 else f"command exited {return_code}",
        now=now,
    )
    return result if deferred else "stale"


async def finish_skill_audit_item(
    session: AsyncSession,
    item: ClaimedWorkItem,
    *,
    return_code: int,
    deferred_retry_seconds: float,
    error_retry_seconds: float,
    now: datetime | None = None,
) -> str:
    skill = await session.get(Skill, uuid.UUID(item.item_id))
    snapshot = (
        await session.get(SkillSnapshot, skill.current_snapshot_id)
        if skill is not None and skill.current_snapshot_id is not None
        else None
    )
    audit_exists = False
    if snapshot is not None and snapshot.content_hash == item.item_revision:
        audit_exists = bool(
            (
                await session.execute(
                    select(
                        completed_skill_audit(
                            skill_id=skill.id,
                            snapshot_id=snapshot.id,
                            content_hash=snapshot.content_hash,
                        )
                    )
                )
            ).scalar_one()
        )
    if (
        skill is None
        or snapshot is None
        or snapshot.content_hash != item.item_revision
        or audit_exists
    ):
        deleted = await delete_item_state(
            session,
            item,
            job_name="skill-maintenance",
        )
        return "completed" if deleted else "stale"
    result = "deferred" if return_code == 0 else "error"
    retry_seconds = (
        deferred_retry_seconds
        if return_code == 0
        else error_retry_delay(
            item,
            initial_retry_seconds=error_retry_seconds,
            maximum_retry_seconds=deferred_retry_seconds,
        )
    )
    deferred = await defer_item_state(
        session,
        item,
        job_name="skill-maintenance",
        retry_seconds=retry_seconds,
        result=result,
        error="" if return_code == 0 else f"command exited {return_code}",
        now=now,
    )
    return result if deferred else "stale"


async def ensure_scheduled_job(
    session: AsyncSession,
    *,
    name: str,
    initial_next_run_at: datetime,
) -> ScheduledJobState:
    await session.execute(
        insert(ScheduledJobState)
        .values(
            name=name,
            next_run_at=initial_next_run_at,
            last_status="scheduled",
            last_error="",
        )
        .on_conflict_do_nothing(index_elements=[ScheduledJobState.name])
    )
    result = await session.execute(
        select(ScheduledJobState).where(ScheduledJobState.name == name)
    )
    return result.scalar_one()


async def mark_scheduled_job_started(
    session: AsyncSession,
    *,
    name: str,
) -> None:
    await session.execute(
        update(ScheduledJobState)
        .where(ScheduledJobState.name == name)
        .values(
            last_started_at=func.now(),
            last_status="running",
            last_error="",
        )
    )


async def mark_scheduled_job_finished(
    session: AsyncSession,
    *,
    name: str,
    next_run_at: datetime,
    return_code: int,
) -> None:
    await session.execute(
        update(ScheduledJobState)
        .where(ScheduledJobState.name == name)
        .values(
            next_run_at=next_run_at,
            last_finished_at=func.now(),
            last_status="completed" if return_code == 0 else "failed",
            last_error="" if return_code == 0 else f"command exited {return_code}",
        )
    )
