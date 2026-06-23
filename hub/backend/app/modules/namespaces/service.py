import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import emit_audit_event
from app.modules.namespaces import repository
from app.modules.namespaces.exceptions import (
    DuplicateNamespaceClaimError,
    InvalidNamespaceClaimTransitionError,
    NamespaceAccessDeniedError,
    NamespaceClaimNotFoundError,
)
from app.modules.namespaces.models import NamespaceClaim
from app.modules.namespaces.schemas import (
    NamespaceClaimCreate,
    NamespaceClaimDecision,
    NamespaceClaimListResponse,
    NamespaceClaimRead,
)
from app.modules.organizations import repository as organizations_repository
from app.modules.organizations.service import require_organization_permission
from app.modules.users.models import User


def namespace_claim_response(claim: NamespaceClaim) -> NamespaceClaimRead:
    return NamespaceClaimRead(
        id=claim.id,
        namespace=claim.namespace,
        ownerOrganizationId=claim.owner_organization_id,
        claimedByUserId=claim.claimed_by_user_id,
        method=claim.method,
        status=claim.status,
        verificationPayload=claim.verification_payload,
        verifiedAt=claim.verified_at,
        expiresAt=claim.expires_at,
        createdAt=claim.created_at,
        updatedAt=claim.updated_at,
    )


async def ensure_can_read_claim(
    session: AsyncSession,
    user: User,
    claim: NamespaceClaim,
) -> None:
    if user.is_superuser or claim.claimed_by_user_id == user.id:
        return
    if claim.owner_organization_id is None:
        raise NamespaceAccessDeniedError("namespace claim access denied")
    membership = await organizations_repository.get_organization_membership(
        session,
        claim.owner_organization_id,
        user.id,
    )
    if membership is None:
        raise NamespaceAccessDeniedError("namespace claim access denied")


async def ensure_can_revoke_claim(
    session: AsyncSession,
    user: User,
    claim: NamespaceClaim,
) -> None:
    if user.is_superuser or claim.claimed_by_user_id == user.id:
        return
    if claim.owner_organization_id is None:
        raise NamespaceAccessDeniedError("namespace claim access denied")
    await require_organization_permission(
        session,
        user,
        claim.owner_organization_id,
        "namespaces.manage",
    )


async def organization_ids_for_user(session: AsyncSession, user: User) -> list[uuid.UUID]:
    if user.is_superuser:
        return []
    rows = await organizations_repository.list_joined_organizations_for_user(session, user.id)
    return [organization.id for organization, _membership in rows]


async def create_namespace_claim(
    session: AsyncSession,
    user: User,
    payload: NamespaceClaimCreate,
) -> NamespaceClaimRead:
    if payload.method in {"manual_partner", "imported_official"} and not user.is_superuser:
        raise NamespaceAccessDeniedError("superuser access required for manual namespace methods")
    if payload.owner_organization_id is not None:
        await require_organization_permission(
            session,
            user,
            payload.owner_organization_id,
            "namespaces.manage",
        )
    if await repository.get_active_claim_by_namespace(session, payload.namespace):
        raise DuplicateNamespaceClaimError("active namespace claim already exists")

    claim = NamespaceClaim(
        namespace=payload.namespace,
        owner_organization_id=payload.owner_organization_id,
        claimed_by_user_id=user.id,
        method=payload.method,
        status="pending",
        verification_payload=payload.verification_payload,
        expires_at=payload.expires_at,
    )
    session.add(claim)
    await session.flush()
    await session.refresh(claim)
    await emit_audit_event(
        session,
        event_type="namespace.claimed",
        subject_type="namespace_claim",
        subject_id=claim.id,
        actor_user_id=user.id,
        organization_id=claim.owner_organization_id,
        metadata={"namespace": claim.namespace, "method": claim.method},
    )
    return namespace_claim_response(claim)


async def list_namespace_claims(
    session: AsyncSession,
    user: User,
) -> NamespaceClaimListResponse:
    claims = await repository.list_claims(
        session,
        user_id=user.id,
        organization_ids=await organization_ids_for_user(session, user),
        include_all=user.is_superuser,
    )
    return NamespaceClaimListResponse(claims=[namespace_claim_response(claim) for claim in claims])


async def get_namespace_claim(
    session: AsyncSession,
    user: User,
    claim_id: uuid.UUID,
) -> NamespaceClaimRead:
    claim = await repository.get_claim_by_id(session, claim_id)
    if claim is None:
        raise NamespaceClaimNotFoundError("namespace claim not found")
    await ensure_can_read_claim(session, user, claim)
    return namespace_claim_response(claim)


async def verify_namespace_claim(
    session: AsyncSession,
    user: User,
    claim_id: uuid.UUID,
    payload: NamespaceClaimDecision,
) -> NamespaceClaimRead:
    claim = await repository.get_claim_by_id(session, claim_id)
    if claim is None:
        raise NamespaceClaimNotFoundError("namespace claim not found")
    if claim.status not in {"pending", "failed"}:
        raise InvalidNamespaceClaimTransitionError("namespace claim cannot be verified")
    claim.status = "verified"
    claim.verified_at = datetime.now(UTC)
    if payload.verification_payload:
        claim.verification_payload = payload.verification_payload
    await session.flush()
    await session.refresh(claim)
    await emit_audit_event(
        session,
        event_type="namespace.verified",
        subject_type="namespace_claim",
        subject_id=claim.id,
        actor_user_id=user.id,
        organization_id=claim.owner_organization_id,
        metadata={"namespace": claim.namespace},
    )
    return namespace_claim_response(claim)


async def fail_namespace_claim(
    session: AsyncSession,
    user: User,
    claim_id: uuid.UUID,
    payload: NamespaceClaimDecision,
) -> NamespaceClaimRead:
    claim = await repository.get_claim_by_id(session, claim_id)
    if claim is None:
        raise NamespaceClaimNotFoundError("namespace claim not found")
    if claim.status != "pending":
        raise InvalidNamespaceClaimTransitionError("only pending namespace claims can fail")
    claim.status = "failed"
    if payload.verification_payload:
        claim.verification_payload = payload.verification_payload
    await session.flush()
    await session.refresh(claim)
    await emit_audit_event(
        session,
        event_type="namespace.failed",
        subject_type="namespace_claim",
        subject_id=claim.id,
        actor_user_id=user.id,
        organization_id=claim.owner_organization_id,
        metadata={"namespace": claim.namespace},
    )
    return namespace_claim_response(claim)


async def revoke_namespace_claim(
    session: AsyncSession,
    user: User,
    claim_id: uuid.UUID,
) -> NamespaceClaimRead:
    claim = await repository.get_claim_by_id(session, claim_id)
    if claim is None:
        raise NamespaceClaimNotFoundError("namespace claim not found")
    await ensure_can_revoke_claim(session, user, claim)
    if claim.status == "revoked":
        raise InvalidNamespaceClaimTransitionError("namespace claim is already revoked")
    claim.status = "revoked"
    await session.flush()
    await session.refresh(claim)
    await emit_audit_event(
        session,
        event_type="namespace.revoked",
        subject_type="namespace_claim",
        subject_id=claim.id,
        actor_user_id=user.id,
        organization_id=claim.owner_organization_id,
        metadata={"namespace": claim.namespace},
    )
    return namespace_claim_response(claim)
