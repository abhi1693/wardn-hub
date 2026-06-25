from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.submissions.exceptions import (
    DuplicatePublishedVersionError,
    InvalidSubmissionTransitionError,
    SubmissionAccessDeniedError,
    SubmissionNotFoundError,
    SubmissionValidationError,
)
from app.modules.submissions.schemas import (
    SubmissionCreate,
    SubmissionListResponse,
    SubmissionRead,
    SubmissionRejectRequest,
    SubmissionUpdate,
)
from app.modules.submissions.service import (
    approve_submission,
    create_submission,
    delete_submission,
    get_submission,
    list_submissions,
    publish_submission,
    reject_submission,
    submit_submission,
    update_submission,
    withdraw_submission,
)
from app.modules.users.dependencies import (
    require_api_token_scopes,
    require_global_moderator,
    require_superuser,
)
from app.modules.users.models import User

router = APIRouter(prefix="/submissions", tags=["submissions"])


def not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def forbidden(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


def bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("", response_model=SubmissionListResponse, operation_id="submissions_list")
async def list_submission_records(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("submissions:read"))],
) -> SubmissionListResponse:
    return await list_submissions(session, current_user)


@router.post(
    "",
    response_model=SubmissionRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="submissions_create",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def create_submission_record(
    payload: SubmissionCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("submissions:write"))],
) -> SubmissionRead:
    try:
        response = await create_submission(session, current_user, payload)
    except DuplicatePublishedVersionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SubmissionAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except SubmissionValidationError as exc:
        raise bad_request(exc) from exc
    await session.commit()
    return response


@router.get(
    "/{submission_id}",
    response_model=SubmissionRead,
    operation_id="submissions_get",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_submission_record(
    submission_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("submissions:read"))],
) -> SubmissionRead:
    try:
        return await get_submission(session, current_user, submission_id)
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except SubmissionAccessDeniedError as exc:
        raise forbidden(exc) from exc


@router.put(
    "/{submission_id}",
    response_model=SubmissionRead,
    operation_id="submissions_update",
)
async def update_submission_record(
    submission_id: UUID,
    payload: SubmissionUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("submissions:write"))],
) -> SubmissionRead:
    try:
        response = await update_submission(session, current_user, submission_id, payload)
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except SubmissionAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except (
        InvalidSubmissionTransitionError,
        DuplicatePublishedVersionError,
        SubmissionValidationError,
    ) as exc:
        raise bad_request(exc) from exc
    await session.commit()
    return response


@router.delete(
    "/{submission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="submissions_delete",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def delete_submission_record(
    submission_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("submissions:write"))],
) -> None:
    try:
        await delete_submission(session, current_user, submission_id)
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except SubmissionAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except InvalidSubmissionTransitionError as exc:
        raise bad_request(exc) from exc
    await session.commit()


@router.post(
    "/{submission_id}/submit",
    response_model=SubmissionRead,
    operation_id="submissions_submit",
    responses={status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse}},
)
async def submit_submission_record(
    submission_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("submissions:write"))],
) -> SubmissionRead:
    try:
        response = await submit_submission(session, current_user, submission_id)
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except SubmissionAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except (
        InvalidSubmissionTransitionError,
        DuplicatePublishedVersionError,
        SubmissionValidationError,
    ) as exc:
        raise bad_request(exc) from exc
    await session.commit()
    return response


@router.post(
    "/{submission_id}/withdraw",
    response_model=SubmissionRead,
    operation_id="submissions_withdraw",
)
async def withdraw_submission_record(
    submission_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("submissions:write"))],
) -> SubmissionRead:
    try:
        response = await withdraw_submission(session, current_user, submission_id)
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except SubmissionAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except InvalidSubmissionTransitionError as exc:
        raise bad_request(exc) from exc
    await session.commit()
    return response


@router.post(
    "/{submission_id}/approve",
    response_model=SubmissionRead,
    operation_id="submissions_approve",
)
async def approve_submission_record(
    submission_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_global_moderator)],
) -> SubmissionRead:
    try:
        response = await approve_submission(session, current_user, submission_id)
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except (InvalidSubmissionTransitionError, DuplicatePublishedVersionError) as exc:
        raise bad_request(exc) from exc
    await session.commit()
    return response


@router.post(
    "/{submission_id}/reject",
    response_model=SubmissionRead,
    operation_id="submissions_reject",
)
async def reject_submission_record(
    submission_id: UUID,
    payload: SubmissionRejectRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_global_moderator)],
) -> SubmissionRead:
    try:
        response = await reject_submission(session, current_user, submission_id, payload.message)
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except InvalidSubmissionTransitionError as exc:
        raise bad_request(exc) from exc
    await session.commit()
    return response


@router.post(
    "/{submission_id}/publish",
    response_model=SubmissionRead,
    operation_id="submissions_publish",
)
async def publish_submission_record(
    submission_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_superuser)],
) -> SubmissionRead:
    try:
        response = await publish_submission(session, current_user, submission_id)
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except (InvalidSubmissionTransitionError, DuplicatePublishedVersionError) as exc:
        raise bad_request(exc) from exc
    await session.commit()
    return response
