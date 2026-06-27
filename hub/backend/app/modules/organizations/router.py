from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.router import commit_response, conflict, forbidden, not_found
from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.organizations.exceptions import (
    DuplicateOrganizationError,
    DuplicateOrganizationRoleError,
    OrganizationAccessDeniedError,
    OrganizationMembershipNotFoundError,
    OrganizationNotFoundError,
    OrganizationRoleNotFoundError,
)
from app.modules.organizations.schemas import (
    OrganizationCreate,
    OrganizationListResponse,
    OrganizationMembershipCreate,
    OrganizationMembershipListResponse,
    OrganizationMembershipRead,
    OrganizationMembershipUpdate,
    OrganizationRead,
    OrganizationRoleCreate,
    OrganizationRoleListResponse,
    OrganizationRoleRead,
    OrganizationUpdate,
)
from app.modules.organizations.service import (
    create_organization,
    create_role,
    get_organization,
    list_memberships,
    list_organizations,
    list_roles,
    update_membership,
    update_organization,
    upsert_membership,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.exceptions import UserNotFoundError
from app.modules.users.models import User

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=OrganizationListResponse, operation_id="organizations_list")
async def list_accessible_organizations(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> OrganizationListResponse:
    return await list_organizations(session, current_user)


@router.post(
    "",
    response_model=OrganizationRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="organizations_create",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def create_organization_route(
    payload: OrganizationCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> OrganizationRead:
    try:
        response = await create_organization(session, current_user, payload)
    except OrganizationAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except DuplicateOrganizationError as exc:
        raise conflict(exc) from exc
    return await commit_response(session, response)


@router.get(
    "/{organization_id}",
    response_model=OrganizationRead,
    operation_id="organizations_get",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def get_organization_route(
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> OrganizationRead:
    try:
        return await get_organization(session, current_user, organization_id)
    except OrganizationNotFoundError as exc:
        raise not_found(exc) from exc
    except OrganizationAccessDeniedError as exc:
        raise forbidden(exc) from exc


@router.put(
    "/{organization_id}",
    response_model=OrganizationRead,
    operation_id="organizations_update",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def update_organization_route(
    organization_id: UUID,
    payload: OrganizationUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> OrganizationRead:
    try:
        response = await update_organization(session, current_user, organization_id, payload)
    except OrganizationNotFoundError as exc:
        raise not_found(exc) from exc
    except OrganizationAccessDeniedError as exc:
        raise forbidden(exc) from exc
    return await commit_response(session, response)


@router.get(
    "/{organization_id}/roles",
    response_model=OrganizationRoleListResponse,
    operation_id="organization_roles_list",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_organization_roles(
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> OrganizationRoleListResponse:
    try:
        return await list_roles(session, current_user, organization_id)
    except OrganizationNotFoundError as exc:
        raise not_found(exc) from exc
    except OrganizationAccessDeniedError as exc:
        raise forbidden(exc) from exc


@router.post(
    "/{organization_id}/roles",
    response_model=OrganizationRoleRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="organization_roles_create",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def create_organization_role(
    organization_id: UUID,
    payload: OrganizationRoleCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> OrganizationRoleRead:
    try:
        response = await create_role(session, current_user, organization_id, payload)
    except OrganizationAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except DuplicateOrganizationRoleError as exc:
        raise conflict(exc) from exc
    return await commit_response(session, response)


@router.get(
    "/{organization_id}/memberships",
    response_model=OrganizationMembershipListResponse,
    operation_id="organization_memberships_list",
    responses={status.HTTP_403_FORBIDDEN: {"model": ErrorResponse}},
)
async def list_organization_memberships_route(
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> OrganizationMembershipListResponse:
    try:
        return await list_memberships(session, current_user, organization_id)
    except OrganizationAccessDeniedError as exc:
        raise forbidden(exc) from exc


@router.post(
    "/{organization_id}/memberships",
    response_model=OrganizationMembershipRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="organization_memberships_upsert",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def upsert_organization_membership_route(
    organization_id: UUID,
    payload: OrganizationMembershipCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> OrganizationMembershipRead:
    try:
        response = await upsert_membership(session, current_user, organization_id, payload)
    except OrganizationAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except (OrganizationRoleNotFoundError, UserNotFoundError) as exc:
        raise not_found(exc) from exc
    return await commit_response(session, response)


@router.patch(
    "/{organization_id}/memberships/{user_id}",
    response_model=OrganizationMembershipRead,
    operation_id="organization_memberships_update",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def update_organization_membership_route(
    organization_id: UUID,
    user_id: UUID,
    payload: OrganizationMembershipUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> OrganizationMembershipRead:
    try:
        response = await update_membership(
            session,
            current_user,
            organization_id,
            user_id,
            payload,
        )
    except OrganizationAccessDeniedError as exc:
        raise forbidden(exc) from exc
    except (OrganizationRoleNotFoundError, OrganizationMembershipNotFoundError) as exc:
        raise not_found(exc) from exc
    return await commit_response(session, response)
