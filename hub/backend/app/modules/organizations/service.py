import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organizations import repository
from app.modules.organizations.exceptions import (
    DuplicateOrganizationError,
    DuplicateOrganizationRoleError,
    OrganizationAccessDeniedError,
    OrganizationMembershipNotFoundError,
    OrganizationNotFoundError,
    OrganizationRoleNotFoundError,
)
from app.modules.organizations.models import (
    DEFAULT_ORGANIZATION_ROLES,
    Organization,
    OrganizationMembership,
    OrganizationRole,
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
from app.modules.users.models import User

ORG_ADMIN_PERMISSIONS = {"organization.manage", "organization.members.manage"}


def normalize_slug(value: str) -> str:
    return value.strip().casefold()


def permissions_for_user(user: User, membership: OrganizationMembership | None) -> set[str]:
    if user.is_superuser:
        return {
            "organization.manage",
            "organization.roles.manage",
            "organization.members.manage",
            "servers.create",
            "servers.update",
            "submissions.approve",
            "namespaces.manage",
            "partner_status.manage",
        }
    if membership is None or not membership.is_active:
        return set()
    return set(membership.role.permissions)


def role_slug_for_user(user: User, membership: OrganizationMembership | None) -> str:
    if user.is_superuser:
        return "owner"
    return membership.role.slug if membership and membership.role else ""


def organization_response(
    organization: Organization,
    *,
    role: str,
) -> OrganizationRead:
    return OrganizationRead(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        status=organization.status,
        currentUserRole=role,
        createdAt=organization.created_at,
        updatedAt=organization.updated_at,
    )


def role_response(role: OrganizationRole) -> OrganizationRoleRead:
    return OrganizationRoleRead(
        id=role.id,
        organizationId=role.organization_id,
        name=role.name,
        slug=role.slug,
        description=role.description,
        permissions=role.permissions,
        isSystemRole=role.is_system_role,
        createdAt=role.created_at,
        updatedAt=role.updated_at,
    )


def membership_response(membership: OrganizationMembership) -> OrganizationMembershipRead:
    return OrganizationMembershipRead(
        id=membership.id,
        organizationId=membership.organization_id,
        userId=membership.user_id,
        roleId=membership.role_id,
        roleSlug=membership.role.slug,
        permissions=membership.role.permissions,
        isActive=membership.is_active,
        createdAt=membership.created_at,
        updatedAt=membership.updated_at,
    )


async def seed_system_roles(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> dict[str, OrganizationRole]:
    roles: dict[str, OrganizationRole] = {}
    for slug, detail in DEFAULT_ORGANIZATION_ROLES.items():
        role = OrganizationRole(
            organization_id=organization_id,
            slug=slug,
            name=detail["name"],
            description=detail["description"],
            permissions=detail["permissions"],
            is_system_role=True,
        )
        session.add(role)
        roles[slug] = role
    await session.flush()
    return roles


async def list_organizations(session: AsyncSession, user: User) -> OrganizationListResponse:
    rows = (
        await repository.list_organizations_for_user(session, user.id)
        if user.is_superuser
        else await repository.list_joined_organizations_for_user(session, user.id)
    )
    return OrganizationListResponse(
        organizations=[
            organization_response(organization, role=role_slug_for_user(user, membership))
            for organization, membership in rows
        ]
    )


async def require_organization_member(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
) -> tuple[Organization, OrganizationMembership | None]:
    organization = await repository.get_organization_by_id(session, organization_id)
    if organization is None or organization.status == "archived":
        raise OrganizationNotFoundError("organization not found")
    membership = await repository.get_organization_membership(session, organization_id, user.id)
    if not user.is_superuser and membership is None:
        raise OrganizationAccessDeniedError("organization access denied")
    return organization, membership


async def require_organization_permission(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    permission: str,
) -> tuple[Organization, OrganizationMembership | None]:
    organization, membership = await require_organization_member(session, user, organization_id)
    if organization.status != "active":
        raise OrganizationAccessDeniedError("organization is not active")
    if permission not in permissions_for_user(user, membership):
        raise OrganizationAccessDeniedError(f"{permission} permission required")
    return organization, membership


async def require_organization_admin(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
) -> tuple[Organization, OrganizationMembership | None]:
    return await require_organization_permission(
        session,
        user,
        organization_id,
        "organization.manage",
    )


async def create_organization(
    session: AsyncSession,
    user: User,
    payload: OrganizationCreate,
) -> OrganizationRead:
    if not user.is_superuser:
        raise OrganizationAccessDeniedError("only superusers can create organizations")
    slug = normalize_slug(payload.slug)
    if await repository.get_organization_by_slug(session, slug):
        raise DuplicateOrganizationError("organization slug already exists")

    organization = Organization(
        name=payload.name.strip(),
        slug=slug,
        status="active",
        created_by_id=user.id,
    )
    session.add(organization)
    await session.flush()
    roles = await seed_system_roles(session, organization.id)
    membership = OrganizationMembership(
        organization_id=organization.id,
        user_id=user.id,
        role_id=roles["owner"].id,
        is_active=True,
    )
    session.add(membership)
    await session.flush()
    await session.refresh(organization)
    return organization_response(organization, role="owner")


async def get_organization(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
) -> OrganizationRead:
    organization, membership = await require_organization_member(session, user, organization_id)
    return organization_response(organization, role=role_slug_for_user(user, membership))


async def update_organization(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    payload: OrganizationUpdate,
) -> OrganizationRead:
    organization, membership = await require_organization_admin(session, user, organization_id)
    organization.name = payload.name.strip()
    organization.status = payload.status
    await session.flush()
    await session.refresh(organization)
    return organization_response(organization, role=role_slug_for_user(user, membership))


async def list_roles(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
) -> OrganizationRoleListResponse:
    await require_organization_member(session, user, organization_id)
    roles = await repository.list_organization_roles(session, organization_id)
    return OrganizationRoleListResponse(roles=[role_response(role) for role in roles])


async def create_role(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    payload: OrganizationRoleCreate,
) -> OrganizationRoleRead:
    await require_organization_permission(
        session,
        user,
        organization_id,
        "organization.roles.manage",
    )
    slug = normalize_slug(payload.slug)
    if await repository.get_organization_role_by_slug(session, organization_id, slug):
        raise DuplicateOrganizationRoleError("organization role slug already exists")
    role = OrganizationRole(
        organization_id=organization_id,
        name=payload.name.strip(),
        slug=slug,
        description=payload.description.strip(),
        permissions=sorted(set(payload.permissions)),
        is_system_role=False,
    )
    session.add(role)
    await session.flush()
    await session.refresh(role)
    return role_response(role)


async def list_memberships(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
) -> OrganizationMembershipListResponse:
    await require_organization_permission(
        session,
        user,
        organization_id,
        "organization.members.manage",
    )
    memberships = await repository.list_organization_memberships(session, organization_id)
    return OrganizationMembershipListResponse(
        memberships=[membership_response(membership) for membership in memberships]
    )


async def upsert_membership(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    payload: OrganizationMembershipCreate,
) -> OrganizationMembershipRead:
    await require_organization_permission(
        session,
        user,
        organization_id,
        "organization.members.manage",
    )
    role = await repository.get_organization_role_by_slug(
        session,
        organization_id,
        normalize_slug(payload.role_slug),
    )
    if role is None:
        raise OrganizationRoleNotFoundError("organization role not found")
    membership = await repository.get_any_organization_membership(
        session,
        organization_id,
        payload.user_id,
    )
    if membership is None:
        membership = OrganizationMembership(
            organization_id=organization_id,
            user_id=payload.user_id,
            role_id=role.id,
            is_active=True,
        )
        membership.role = role
        session.add(membership)
    else:
        membership.role_id = role.id
        membership.role = role
        membership.is_active = True
    await session.flush()
    await session.refresh(membership)
    return membership_response(membership)


async def update_membership(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    target_user_id: uuid.UUID,
    payload: OrganizationMembershipUpdate,
) -> OrganizationMembershipRead:
    await require_organization_permission(
        session,
        user,
        organization_id,
        "organization.members.manage",
    )
    membership = await repository.get_any_organization_membership(
        session,
        organization_id,
        target_user_id,
    )
    if membership is None:
        raise OrganizationMembershipNotFoundError("organization membership not found")
    role = await repository.get_organization_role_by_slug(
        session,
        organization_id,
        normalize_slug(payload.role_slug),
    )
    if role is None:
        raise OrganizationRoleNotFoundError("organization role not found")
    membership.role_id = role.id
    membership.role = role
    membership.is_active = payload.is_active
    await session.flush()
    await session.refresh(membership)
    return membership_response(membership)
