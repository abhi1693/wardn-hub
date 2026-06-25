from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.partners.exceptions import (
    DuplicatePartnerSupportError,
    InvalidPartnerSupportError,
    PartnerOrganizationNotFoundError,
    PartnerSupportNotFoundError,
)
from app.modules.partners.schemas import (
    PartnerOrganizationListResponse,
    PartnerOrganizationRead,
    PartnerOrganizationUpdate,
    PartnerServerSupportCreate,
    PartnerServerSupportListResponse,
    PartnerServerSupportRead,
    PartnerServerSupportUpdate,
)
from app.modules.partners.service import (
    create_server_support,
    list_partner_organizations,
    list_server_support,
    update_partner_organization,
    update_server_support,
)
from app.modules.users.dependencies import get_current_user, require_global_partner_manager
from app.modules.users.models import User

router = APIRouter(prefix="/partners", tags=["partners"])


def not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "",
    response_model=PartnerOrganizationListResponse,
    operation_id="partners_list",
)
async def list_partner_organization_records(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> PartnerOrganizationListResponse:
    return await list_partner_organizations(session)


@router.patch(
    "/organizations/{organization_id}",
    response_model=PartnerOrganizationRead,
    operation_id="partners_update_organization",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def update_partner_organization_record(
    organization_id: UUID,
    payload: PartnerOrganizationUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_global_partner_manager)],
) -> PartnerOrganizationRead:
    try:
        response = await update_partner_organization(
            session,
            current_user,
            organization_id,
            payload,
        )
    except PartnerOrganizationNotFoundError as exc:
        raise not_found(exc) from exc
    await session.commit()
    return response


@router.get(
    "/organizations/{organization_id}/server-support",
    response_model=PartnerServerSupportListResponse,
    operation_id="partners_server_support_list",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def list_partner_server_support_records(
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> PartnerServerSupportListResponse:
    try:
        return await list_server_support(session, organization_id)
    except PartnerOrganizationNotFoundError as exc:
        raise not_found(exc) from exc


@router.post(
    "/organizations/{organization_id}/server-support",
    response_model=PartnerServerSupportRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="partners_server_support_create",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def create_partner_server_support_record(
    organization_id: UUID,
    payload: PartnerServerSupportCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_global_partner_manager)],
) -> PartnerServerSupportRead:
    try:
        response = await create_server_support(session, current_user, organization_id, payload)
    except PartnerOrganizationNotFoundError as exc:
        raise not_found(exc) from exc
    except InvalidPartnerSupportError as exc:
        raise bad_request(exc) from exc
    except DuplicatePartnerSupportError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()
    return response


@router.patch(
    "/server-support/{support_id}",
    response_model=PartnerServerSupportRead,
    operation_id="partners_server_support_update",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def update_partner_server_support_record(
    support_id: UUID,
    payload: PartnerServerSupportUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_global_partner_manager)],
) -> PartnerServerSupportRead:
    try:
        response = await update_server_support(session, current_user, support_id, payload)
    except PartnerSupportNotFoundError as exc:
        raise not_found(exc) from exc
    await session.commit()
    return response
