import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import emit_audit_event
from app.modules.organizations import repository as organizations_repository
from app.modules.organizations.models import Organization
from app.modules.partners import repository
from app.modules.partners.exceptions import (
    DuplicatePartnerSupportError,
    InvalidPartnerSupportError,
    PartnerOrganizationNotFoundError,
    PartnerSupportNotFoundError,
)
from app.modules.partners.models import OrganizationServerSupport
from app.modules.partners.schemas import (
    PartnerOrganizationListResponse,
    PartnerOrganizationRead,
    PartnerOrganizationUpdate,
    PartnerServerSupportCreate,
    PartnerServerSupportListResponse,
    PartnerServerSupportRead,
    PartnerServerSupportUpdate,
)
from app.modules.users.models import User


def partner_organization_response(organization: Organization) -> PartnerOrganizationRead:
    return PartnerOrganizationRead(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        status=organization.status,
        isPartner=organization.is_partner,
        partnerStatus=organization.partner_status,
        partnerTier=organization.partner_tier,
        partnerSupportLevel=organization.partner_support_level or "compatible",
        websiteUrl=organization.website_url,
        supportEmail=organization.support_email,
        partnerProfile=organization.partner_profile,
        createdAt=organization.created_at,
        updatedAt=organization.updated_at,
    )


def server_support_response(support: OrganizationServerSupport) -> PartnerServerSupportRead:
    return PartnerServerSupportRead(
        id=support.id,
        organizationId=support.organization_id,
        serverName=support.server_name,
        supportLevel=support.support_level,
        supportStatus=support.support_status,
        supportUrl=support.support_url,
        docsUrl=support.docs_url,
        contactPolicy=support.contact_policy,
        startsAt=support.starts_at,
        endsAt=support.ends_at,
        createdAt=support.created_at,
        updatedAt=support.updated_at,
    )


async def require_organization(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> Organization:
    organization = await organizations_repository.get_organization_by_id(session, organization_id)
    if organization is None or organization.status == "archived":
        raise PartnerOrganizationNotFoundError("partner organization not found")
    return organization


async def list_partner_organizations(
    session: AsyncSession,
) -> PartnerOrganizationListResponse:
    organizations = await repository.list_partner_organizations(session)
    return PartnerOrganizationListResponse(
        organizations=[
            partner_organization_response(organization) for organization in organizations
        ]
    )


async def update_partner_organization(
    session: AsyncSession,
    actor: User,
    organization_id: uuid.UUID,
    payload: PartnerOrganizationUpdate,
) -> PartnerOrganizationRead:
    organization = await require_organization(session, organization_id)
    if "is_partner" in payload.model_fields_set and payload.is_partner is not None:
        organization.is_partner = payload.is_partner
    if "partner_status" in payload.model_fields_set and payload.partner_status is not None:
        organization.partner_status = payload.partner_status
    if "partner_tier" in payload.model_fields_set and payload.partner_tier is not None:
        organization.partner_tier = payload.partner_tier
    if (
        "partner_support_level" in payload.model_fields_set
        and payload.partner_support_level is not None
    ):
        organization.partner_support_level = payload.partner_support_level
    if "website_url" in payload.model_fields_set and payload.website_url is not None:
        organization.website_url = payload.website_url.strip()
    if "support_email" in payload.model_fields_set:
        organization.support_email = str(payload.support_email or "")
    if "partner_profile" in payload.model_fields_set and payload.partner_profile is not None:
        organization.partner_profile = payload.partner_profile
    if (
        "partner_internal_notes" in payload.model_fields_set
        and payload.partner_internal_notes is not None
    ):
        organization.partner_internal_notes = payload.partner_internal_notes.strip()

    await session.flush()
    await session.refresh(organization)
    await emit_audit_event(
        session,
        event_type="partner.updated",
        subject_type="organization",
        subject_id=organization.id,
        actor_user_id=actor.id,
        organization_id=organization.id,
        metadata={
            "partnerStatus": organization.partner_status,
            "partnerTier": organization.partner_tier,
            "partnerSupportLevel": organization.partner_support_level,
            "isPartner": organization.is_partner,
        },
    )
    return partner_organization_response(organization)


async def list_server_support(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> PartnerServerSupportListResponse:
    await require_organization(session, organization_id)
    support_records = await repository.list_support_for_organization(session, organization_id)
    return PartnerServerSupportListResponse(
        support=[server_support_response(support) for support in support_records]
    )


async def create_server_support(
    session: AsyncSession,
    actor: User,
    organization_id: uuid.UUID,
    payload: PartnerServerSupportCreate,
) -> PartnerServerSupportRead:
    organization = await require_organization(session, organization_id)
    if not organization.is_partner:
        raise InvalidPartnerSupportError("organization is not a partner")
    if await repository.get_support_by_organization_and_server(
        session,
        organization_id,
        payload.server_name,
    ):
        raise DuplicatePartnerSupportError("server support record already exists")

    support = OrganizationServerSupport(
        organization_id=organization_id,
        server_name=payload.server_name,
        support_level=payload.support_level,
        support_status=payload.support_status,
        support_url=payload.support_url.strip(),
        docs_url=payload.docs_url.strip(),
        contact_policy=payload.contact_policy,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        internal_notes=payload.internal_notes.strip(),
    )
    session.add(support)
    await session.flush()
    await session.refresh(support)
    await emit_audit_event(
        session,
        event_type="partner.support.created",
        subject_type="organization_server_support",
        subject_id=support.id,
        actor_user_id=actor.id,
        organization_id=organization_id,
        metadata={"serverName": support.server_name, "supportLevel": support.support_level},
    )
    return server_support_response(support)


async def update_server_support(
    session: AsyncSession,
    actor: User,
    support_id: uuid.UUID,
    payload: PartnerServerSupportUpdate,
) -> PartnerServerSupportRead:
    support = await repository.get_support_by_id(session, support_id)
    if support is None:
        raise PartnerSupportNotFoundError("partner support record not found")
    if "support_level" in payload.model_fields_set and payload.support_level is not None:
        support.support_level = payload.support_level
    if "support_status" in payload.model_fields_set and payload.support_status is not None:
        support.support_status = payload.support_status
    if "support_url" in payload.model_fields_set and payload.support_url is not None:
        support.support_url = payload.support_url.strip()
    if "docs_url" in payload.model_fields_set and payload.docs_url is not None:
        support.docs_url = payload.docs_url.strip()
    if "contact_policy" in payload.model_fields_set and payload.contact_policy is not None:
        support.contact_policy = payload.contact_policy
    if "starts_at" in payload.model_fields_set:
        support.starts_at = payload.starts_at
    if "ends_at" in payload.model_fields_set:
        support.ends_at = payload.ends_at
    if "internal_notes" in payload.model_fields_set and payload.internal_notes is not None:
        support.internal_notes = payload.internal_notes.strip()

    await session.flush()
    await session.refresh(support)
    await emit_audit_event(
        session,
        event_type="partner.support.updated",
        subject_type="organization_server_support",
        subject_id=support.id,
        actor_user_id=actor.id,
        organization_id=support.organization_id,
        metadata={"serverName": support.server_name, "supportStatus": support.support_status},
    )
    return server_support_response(support)
