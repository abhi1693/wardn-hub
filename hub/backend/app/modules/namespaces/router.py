from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.namespaces.exceptions import (
    DuplicateNamespaceClaimError,
    InvalidNamespaceClaimTransitionError,
    NamespaceAccessDeniedError,
    NamespaceClaimNotFoundError,
)
from app.modules.namespaces.schemas import (
    NamespaceClaimCreate,
    NamespaceClaimDecision,
    NamespaceClaimListResponse,
    NamespaceClaimRead,
)
from app.modules.namespaces.service import (
    create_namespace_claim,
    fail_namespace_claim,
    get_namespace_claim,
    list_namespace_claims,
    revoke_namespace_claim,
    verify_namespace_claim,
)
from app.modules.users.dependencies import get_current_user, require_superuser
from app.modules.users.models import User

router = APIRouter(prefix="/namespaces", tags=["namespaces"])


def not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def forbidden(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


def bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/claims",
    response_model=NamespaceClaimListResponse,
    operation_id="namespace_claims_list",
)
async def list_namespace_claim_records(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> NamespaceClaimListResponse:
    return await list_namespace_claims(session, current_user)


@router.post(
    "/claims",
    response_model=NamespaceClaimRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="namespace_claims_create",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def create_namespace_claim_record(
    payload: NamespaceClaimCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> NamespaceClaimRead:
    try:
        response = await create_namespace_claim(session, current_user, payload)
    except NamespaceAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except DuplicateNamespaceClaimError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()
    return response


@router.get(
    "/claims/{claim_id}",
    response_model=NamespaceClaimRead,
    operation_id="namespace_claims_get",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_namespace_claim_record(
    claim_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> NamespaceClaimRead:
    try:
        return await get_namespace_claim(session, current_user, claim_id)
    except NamespaceClaimNotFoundError as exc:
        raise not_found(exc) from exc
    except NamespaceAccessDeniedError as exc:
        raise forbidden(exc) from exc


@router.post(
    "/claims/{claim_id}/verify",
    response_model=NamespaceClaimRead,
    operation_id="namespace_claims_verify",
)
async def verify_namespace_claim_record(
    claim_id: UUID,
    payload: NamespaceClaimDecision,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_superuser)],
) -> NamespaceClaimRead:
    try:
        response = await verify_namespace_claim(session, current_user, claim_id, payload)
    except NamespaceClaimNotFoundError as exc:
        raise not_found(exc) from exc
    except InvalidNamespaceClaimTransitionError as exc:
        raise bad_request(exc) from exc
    await session.commit()
    return response


@router.post(
    "/claims/{claim_id}/fail",
    response_model=NamespaceClaimRead,
    operation_id="namespace_claims_fail",
)
async def fail_namespace_claim_record(
    claim_id: UUID,
    payload: NamespaceClaimDecision,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_superuser)],
) -> NamespaceClaimRead:
    try:
        response = await fail_namespace_claim(session, current_user, claim_id, payload)
    except NamespaceClaimNotFoundError as exc:
        raise not_found(exc) from exc
    except InvalidNamespaceClaimTransitionError as exc:
        raise bad_request(exc) from exc
    await session.commit()
    return response


@router.post(
    "/claims/{claim_id}/revoke",
    response_model=NamespaceClaimRead,
    operation_id="namespace_claims_revoke",
)
async def revoke_namespace_claim_record(
    claim_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> NamespaceClaimRead:
    try:
        response = await revoke_namespace_claim(session, current_user, claim_id)
    except NamespaceClaimNotFoundError as exc:
        raise not_found(exc) from exc
    except NamespaceAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except InvalidNamespaceClaimTransitionError as exc:
        raise bad_request(exc) from exc
    await session.commit()
    return response
