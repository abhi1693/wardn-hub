import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.router import (
    bad_request,
    commit_response,
    commit_session,
    conflict,
    forbidden,
    not_found,
)
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
    SubmissionOwnerScope,
    SubmissionRead,
    SubmissionRejectRequest,
    SubmissionStatus,
    SubmissionSubmitRequest,
    SubmissionUpdate,
)
from app.modules.submissions.service import (
    approve_submission,
    approve_submission_by_system,
    create_submission,
    delete_submission,
    get_submission,
    get_submission_for_system_review,
    list_submissions,
    list_submissions_for_system_review,
    publish_submission,
    publish_submission_by_system,
    reject_submission,
    reject_submission_by_system,
    submit_submission_request,
    update_submission,
    withdraw_submission,
)
from app.modules.users.dependencies import (
    get_request_api_token,
    require_api_token_scopes,
    require_global_moderator_scopes,
    require_superuser_scopes,
)
from app.modules.users.models import User

router = APIRouter(prefix="/submissions", tags=["submissions"])
system_review_router = APIRouter(
    prefix="/system/review/submissions",
    tags=["system-review"],
    include_in_schema=False,
)
SYSTEM_REVIEW_SECRET_HEADER = "X-Wardn-System-Review-Secret"


def require_system_review_secret(
    supplied_secret: Annotated[str | None, Header(alias=SYSTEM_REVIEW_SECRET_HEADER)] = None,
) -> None:
    configured_secret = get_settings().system_review_secret.strip()
    if not configured_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="system review is not configured",
        )
    if not supplied_secret or not hmac.compare_digest(supplied_secret, configured_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="system review access denied",
        )


@router.get("", response_model=SubmissionListResponse, operation_id="submissions_list")
async def list_submission_records(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("submissions:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(alias="perPage", ge=1, le=100)] = 20,
    submission_status: Annotated[SubmissionStatus | None, Query(alias="status")] = None,
    owner_scope: Annotated[SubmissionOwnerScope, Query(alias="ownerScope")] = "mine",
) -> SubmissionListResponse:
    return await list_submissions(
        session,
        current_user,
        api_token=get_request_api_token(request),
        page=page,
        per_page=per_page,
        status=submission_status,
        owner_scope=owner_scope,
    )


@router.post(
    "",
    response_model=SubmissionRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="submissions_create",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def create_submission_record(
    request: Request,
    payload: SubmissionCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("submissions:write"))],
) -> SubmissionRead:
    try:
        response = await create_submission(
            session,
            current_user,
            payload,
            api_token=get_request_api_token(request),
        )
    except DuplicatePublishedVersionError as exc:
        raise conflict(exc) from exc
    except SubmissionAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except SubmissionValidationError as exc:
        raise bad_request(exc) from exc
    return await commit_response(session, response)


@router.post(
    "/submit",
    response_model=SubmissionRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="submissions_create_and_submit",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def create_and_submit_submission_record(
    request: Request,
    payload: SubmissionSubmitRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("submissions:write"))],
) -> SubmissionRead:
    try:
        response = await submit_submission_request(
            session,
            current_user,
            payload,
            api_token=get_request_api_token(request),
        )
    except DuplicatePublishedVersionError as exc:
        raise conflict(exc) from exc
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except SubmissionAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except (InvalidSubmissionTransitionError, SubmissionValidationError) as exc:
        raise bad_request(exc) from exc
    return await commit_response(session, response)


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
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("submissions:read"))],
) -> SubmissionRead:
    try:
        return await get_submission(
            session,
            current_user,
            submission_id,
            api_token=get_request_api_token(request),
        )
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
    request: Request,
    payload: SubmissionUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("submissions:write"))],
) -> SubmissionRead:
    try:
        response = await update_submission(
            session,
            current_user,
            submission_id,
            payload,
            api_token=get_request_api_token(request),
        )
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
    return await commit_response(session, response)


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
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("submissions:write"))],
) -> None:
    try:
        await delete_submission(
            session,
            current_user,
            submission_id,
            api_token=get_request_api_token(request),
        )
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except SubmissionAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except InvalidSubmissionTransitionError as exc:
        raise bad_request(exc) from exc
    await commit_session(session)


@router.post(
    "/{submission_id}/withdraw",
    response_model=SubmissionRead,
    operation_id="submissions_withdraw",
)
async def withdraw_submission_record(
    submission_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_api_token_scopes("submissions:write"))],
) -> SubmissionRead:
    try:
        response = await withdraw_submission(
            session,
            current_user,
            submission_id,
            api_token=get_request_api_token(request),
        )
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except SubmissionAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except InvalidSubmissionTransitionError as exc:
        raise bad_request(exc) from exc
    return await commit_response(session, response)


@router.post(
    "/{submission_id}/approve",
    response_model=SubmissionRead,
    operation_id="submissions_approve",
)
async def approve_submission_record(
    submission_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_global_moderator_scopes("submissions:moderate"))],
) -> SubmissionRead:
    try:
        response = await approve_submission(
            session,
            current_user,
            submission_id,
            api_token=get_request_api_token(request),
        )
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except (
        InvalidSubmissionTransitionError,
        DuplicatePublishedVersionError,
        SubmissionValidationError,
    ) as exc:
        raise bad_request(exc) from exc
    return await commit_response(session, response)


@router.post(
    "/{submission_id}/reject",
    response_model=SubmissionRead,
    operation_id="submissions_reject",
)
async def reject_submission_record(
    submission_id: UUID,
    request: Request,
    payload: SubmissionRejectRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_global_moderator_scopes("submissions:moderate"))],
) -> SubmissionRead:
    try:
        response = await reject_submission(
            session,
            current_user,
            submission_id,
            payload.message,
            api_token=get_request_api_token(request),
        )
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except InvalidSubmissionTransitionError as exc:
        raise bad_request(exc) from exc
    return await commit_response(session, response)


@router.post(
    "/{submission_id}/publish",
    response_model=SubmissionRead,
    operation_id="submissions_publish",
)
async def publish_submission_record(
    submission_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_superuser_scopes("submissions:publish"))],
) -> SubmissionRead:
    try:
        response = await publish_submission(
            session,
            current_user,
            submission_id,
            api_token=get_request_api_token(request),
        )
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except (
        InvalidSubmissionTransitionError,
        DuplicatePublishedVersionError,
        SubmissionValidationError,
    ) as exc:
        raise bad_request(exc) from exc
    return await commit_response(session, response)


@system_review_router.get(
    "",
    response_model=SubmissionListResponse,
    operation_id="system_review_submissions_list",
)
async def list_system_review_submission_records(
    _system_review_access: Annotated[None, Depends(require_system_review_secret)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(alias="perPage", ge=1, le=100)] = 20,
    submission_status: Annotated[SubmissionStatus | None, Query(alias="status")] = "submitted",
) -> SubmissionListResponse:
    return await list_submissions_for_system_review(
        session,
        page=page,
        per_page=per_page,
        status=submission_status,
    )


@system_review_router.get(
    "/{submission_id}",
    response_model=SubmissionRead,
    operation_id="system_review_submissions_get",
)
async def get_system_review_submission_record(
    submission_id: UUID,
    _system_review_access: Annotated[None, Depends(require_system_review_secret)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SubmissionRead:
    try:
        return await get_submission_for_system_review(session, submission_id)
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc


@system_review_router.post(
    "/{submission_id}/approve",
    response_model=SubmissionRead,
    operation_id="system_review_submissions_approve",
)
async def approve_system_review_submission_record(
    submission_id: UUID,
    _system_review_access: Annotated[None, Depends(require_system_review_secret)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SubmissionRead:
    try:
        response = await approve_submission_by_system(session, submission_id)
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except (
        InvalidSubmissionTransitionError,
        DuplicatePublishedVersionError,
        SubmissionValidationError,
    ) as exc:
        raise bad_request(exc) from exc
    return await commit_response(session, response)


@system_review_router.post(
    "/{submission_id}/reject",
    response_model=SubmissionRead,
    operation_id="system_review_submissions_reject",
)
async def reject_system_review_submission_record(
    submission_id: UUID,
    payload: SubmissionRejectRequest,
    _system_review_access: Annotated[None, Depends(require_system_review_secret)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SubmissionRead:
    try:
        response = await reject_submission_by_system(session, submission_id, payload.message)
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except InvalidSubmissionTransitionError as exc:
        raise bad_request(exc) from exc
    return await commit_response(session, response)


@system_review_router.post(
    "/{submission_id}/publish",
    response_model=SubmissionRead,
    operation_id="system_review_submissions_publish",
)
async def publish_system_review_submission_record(
    submission_id: UUID,
    _system_review_access: Annotated[None, Depends(require_system_review_secret)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SubmissionRead:
    try:
        response = await publish_submission_by_system(session, submission_id)
    except SubmissionNotFoundError as exc:
        raise not_found(exc) from exc
    except (
        InvalidSubmissionTransitionError,
        DuplicatePublishedVersionError,
        SubmissionValidationError,
    ) as exc:
        raise bad_request(exc) from exc
    return await commit_response(session, response)
