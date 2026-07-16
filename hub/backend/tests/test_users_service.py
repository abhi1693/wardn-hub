from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.security import verify_api_token, verify_password
from app.modules.users import service
from app.modules.users.exceptions import (
    BootstrapUserExistsError,
    DuplicateUserError,
    InvalidAPITokenScopeError,
    InvalidLoginError,
    InvalidUserRoleUpdateError,
    OIDCAuthenticationError,
)
from app.modules.users.models import User, UserAPIToken, UserExternalIdentity
from app.modules.users.oidc import OIDCIdentity
from app.modules.users.schemas import (
    LoginRequest,
    UserAdminUpdate,
    UserAPITokenCreate,
    UserAPITokenUpdate,
    UserCreate,
)


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False
        self.flushed = False

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushed = True
        now = datetime(2026, 6, 23, tzinfo=UTC)
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()
            if getattr(instance, "created_at", None) is None:
                instance.created_at = now
            if getattr(instance, "updated_at", None) is None:
                instance.updated_at = now

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, instance) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = uuid4()


def user_payload() -> UserCreate:
    return UserCreate(
        email="ADMIN@EXAMPLE.COM",
        password="correct horse battery staple",
        first_name="Admin",
        last_name="User",
    )


def test_list_auth_providers_reports_configured_oidc_policy(monkeypatch) -> None:
    settings = SimpleNamespace(
        auth_providers=["local", "oidc"],
        auth_default_provider="oidc",
        oidc_provider_name="Company SSO",
        oidc_issuer_url="https://identity.example.com",
        oidc_client_id="wardn-hub",
        oidc_client_secret="secret",
        oidc_auto_create_users=False,
    )
    monkeypatch.setattr(service, "get_settings", lambda: settings)

    response = service.list_auth_providers()

    assert response.default_provider == "oidc"
    assert [provider.provider for provider in response.providers] == ["local", "oidc"]
    assert response.providers[1].label == "Company SSO"
    assert response.providers[1].sign_in_enabled is True
    assert response.providers[1].sign_up_enabled is False


@pytest.mark.asyncio
async def test_create_user_normalizes_email_and_hashes_password(monkeypatch) -> None:
    async def missing_user(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_user_by_email", missing_user)

    user = await service.create_user(FakeSession(), user_payload(), is_superuser=True)

    assert user.email == "admin@example.com"
    assert user.is_superuser is True
    assert user.local_credentials is not None
    assert verify_password(
        "correct horse battery staple",
        user.local_credentials.password_hash,
    )


@pytest.mark.asyncio
async def test_create_user_rejects_duplicate_email(monkeypatch) -> None:
    async def existing_user(*args, **kwargs):
        return object()

    monkeypatch.setattr(service.repository, "get_user_by_email", existing_user)

    with pytest.raises(DuplicateUserError):
        await service.create_user(FakeSession(), user_payload())


@pytest.mark.asyncio
async def test_oidc_auth_links_existing_user_by_email(monkeypatch) -> None:
    user = User(
        email="admin@example.com",
        first_name="Admin",
        last_name="User",
        is_active=True,
    )
    user.id = uuid4()

    async def missing_identity(_session, provider, subject):
        assert provider == service.oidc_identity_provider_key("https://issuer.example.com")
        assert subject == "user_123"
        return None

    async def existing_user(*args, **kwargs):
        return user

    async def no_oidc_identity_for_user(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_external_identity", missing_identity)
    monkeypatch.setattr(service.repository, "get_user_by_email", existing_user)
    monkeypatch.setattr(
        service.repository,
        "get_user_external_identity_for_provider",
        no_oidc_identity_for_user,
    )
    session = FakeSession()

    response = await service.authenticate_oidc_identity(
        session,
        OIDCIdentity(
            subject="user_123",
            email="ADMIN@EXAMPLE.COM",
            first_name="",
            last_name="",
            issuer="https://issuer.example.com",
        ),
        auto_create_users=True,
        superuser_emails=[],
    )

    identities = [item for item in session.added if isinstance(item, UserExternalIdentity)]
    assert response is user
    assert identities[0].provider == service.oidc_identity_provider_key(
        "https://issuer.example.com"
    )
    assert identities[0].subject == "user_123"
    assert identities[0].email == "admin@example.com"


@pytest.mark.asyncio
async def test_oidc_auth_updates_existing_identity_profile_names(monkeypatch) -> None:
    user = User(
        email="member@example.com",
        first_name="Old",
        last_name="Name",
        is_active=True,
    )
    user.id = uuid4()
    identity = UserExternalIdentity(
        user_id=user.id,
        provider=service.oidc_identity_provider_key("https://issuer.example.com"),
        subject="user_123",
        email="member@example.com",
    )
    identity.user = user

    async def existing_identity(*args, **kwargs):
        return identity

    monkeypatch.setattr(service.repository, "get_external_identity", existing_identity)

    response = await service.authenticate_oidc_identity(
        FakeSession(),
        OIDCIdentity(
            subject="user_123",
            email="MEMBER@EXAMPLE.COM",
            first_name="Member",
            last_name="User",
            issuer="https://issuer.example.com",
        ),
        auto_create_users=True,
        superuser_emails=["member@example.com"],
    )

    assert response is user
    assert user.first_name == "Member"
    assert user.last_name == "User"
    assert user.is_superuser is True
    assert identity.email == "member@example.com"


@pytest.mark.asyncio
async def test_oidc_existing_subject_updates_canonical_user_and_identity_email(monkeypatch) -> None:
    user = User(email="old@example.com", is_active=True)
    user.id = uuid4()
    identity = UserExternalIdentity(
        user_id=user.id,
        provider=service.oidc_identity_provider_key("https://issuer.example.com"),
        subject="subject-1",
        email="old@example.com",
    )
    identity.user = user

    async def existing_identity(*args, **kwargs):
        return identity

    async def email_is_available(_session, email, *, for_update=False):
        assert email == "new@example.com"
        assert for_update is False
        return None

    monkeypatch.setattr(service.repository, "get_external_identity", existing_identity)
    monkeypatch.setattr(service.repository, "get_user_by_email", email_is_available)

    result = await service.authenticate_oidc_identity(
        FakeSession(),
        OIDCIdentity(
            email="NEW@EXAMPLE.COM",
            first_name="Member",
            last_name="User",
            subject="subject-1",
            issuer="https://issuer.example.com",
        ),
        auto_create_users=True,
        superuser_emails=[],
    )

    assert result is user
    assert user.email == "new@example.com"
    assert identity.email == "new@example.com"


@pytest.mark.asyncio
async def test_oidc_email_reassignment_frees_old_address_for_new_subject(monkeypatch) -> None:
    original_user = User(email="old@example.com", is_active=True)
    original_user.id = uuid4()
    original_identity = UserExternalIdentity(
        user_id=original_user.id,
        provider=service.oidc_identity_provider_key("https://issuer.example.com"),
        subject="subject-1",
        email="old@example.com",
    )
    original_identity.user = original_user

    async def identity_by_subject(_session, _provider, subject):
        return original_identity if subject == "subject-1" else None

    async def user_by_current_email(_session, email, *, for_update=False):
        if email == "old@example.com":
            assert for_update is True
        return original_user if email == original_user.email else None

    monkeypatch.setattr(service.repository, "get_external_identity", identity_by_subject)
    monkeypatch.setattr(service.repository, "get_user_by_email", user_by_current_email)
    session = FakeSession()

    await service.authenticate_oidc_identity(
        session,
        OIDCIdentity(
            email="new@example.com",
            first_name="Original",
            last_name="User",
            subject="subject-1",
            issuer="https://issuer.example.com",
        ),
        auto_create_users=True,
        superuser_emails=[],
    )
    replacement_user = await service.authenticate_oidc_identity(
        session,
        OIDCIdentity(
            email="old@example.com",
            first_name="Replacement",
            last_name="User",
            subject="subject-2",
            issuer="https://issuer.example.com",
        ),
        auto_create_users=True,
        superuser_emails=[],
    )

    assert original_user.email == "new@example.com"
    assert original_identity.email == "new@example.com"
    assert replacement_user is not original_user
    assert replacement_user.email == "old@example.com"


@pytest.mark.asyncio
async def test_oidc_existing_subject_rejects_email_owned_by_another_user(monkeypatch) -> None:
    user = User(email="old@example.com", is_active=True)
    user.id = uuid4()
    conflicting_user = User(email="taken@example.com", is_active=True)
    conflicting_user.id = uuid4()
    identity = UserExternalIdentity(
        user_id=user.id,
        provider=service.oidc_identity_provider_key("https://issuer.example.com"),
        subject="subject-1",
        email="old@example.com",
    )
    identity.user = user

    async def existing_identity(*args, **kwargs):
        return identity

    async def conflicting_email(*args, **kwargs):
        return conflicting_user

    monkeypatch.setattr(service.repository, "get_external_identity", existing_identity)
    monkeypatch.setattr(service.repository, "get_user_by_email", conflicting_email)

    with pytest.raises(OIDCAuthenticationError, match="already linked to another user"):
        await service.authenticate_oidc_identity(
            FakeSession(),
            OIDCIdentity(
                email="taken@example.com",
                first_name="Member",
                last_name="User",
                subject="subject-1",
                issuer="https://issuer.example.com",
            ),
            auto_create_users=True,
            superuser_emails=[],
        )

    assert user.email == "old@example.com"
    assert identity.email == "old@example.com"


@pytest.mark.asyncio
async def test_unseen_oidc_subject_cannot_claim_recycled_email_before_owner_returns(
    monkeypatch,
) -> None:
    user = User(email="recycled@example.com", is_active=True)
    user.id = uuid4()
    original_identity = UserExternalIdentity(
        user_id=user.id,
        provider=service.oidc_identity_provider_key("https://issuer.example.com"),
        subject="original-subject",
        email="recycled@example.com",
    )
    original_identity.user = user

    async def unseen_subject(*args, **kwargs):
        return None

    async def user_with_stale_email(*args, **kwargs):
        return user

    async def existing_provider_identity(*args, **kwargs):
        return original_identity

    monkeypatch.setattr(service.repository, "get_external_identity", unseen_subject)
    monkeypatch.setattr(service.repository, "get_user_by_email", user_with_stale_email)
    monkeypatch.setattr(
        service.repository,
        "get_user_external_identity_for_provider",
        existing_provider_identity,
    )

    with pytest.raises(OIDCAuthenticationError, match="already linked to another identity"):
        await service.authenticate_oidc_identity(
            FakeSession(),
            OIDCIdentity(
                email="recycled@example.com",
                first_name="New",
                last_name="Owner",
                subject="different-subject",
                issuer="https://issuer.example.com",
            ),
            auto_create_users=True,
            superuser_emails=[],
        )

    assert user.email == "recycled@example.com"
    assert original_identity.subject == "original-subject"


@pytest.mark.asyncio
async def test_oidc_auth_creates_user_without_local_credentials(monkeypatch) -> None:
    async def missing_identity(*args, **kwargs):
        return None

    async def missing_user(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_external_identity", missing_identity)
    monkeypatch.setattr(service.repository, "get_user_by_email", missing_user)
    session = FakeSession()

    user = await service.authenticate_oidc_identity(
        session,
        OIDCIdentity(
            subject="user_123",
            email="member@example.com",
            first_name="Member",
            last_name="User",
            issuer="https://issuer.example.com",
        ),
        auto_create_users=True,
        superuser_emails=[],
    )

    assert user.email == "member@example.com"
    assert user.local_credentials is None
    assert user.is_superuser is False


@pytest.mark.asyncio
async def test_oidc_auth_rejects_missing_user_when_auto_create_is_disabled(monkeypatch) -> None:
    async def missing_identity(*args, **kwargs):
        return None

    async def missing_user(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_external_identity", missing_identity)
    monkeypatch.setattr(service.repository, "get_user_by_email", missing_user)

    with pytest.raises(OIDCAuthenticationError, match="auto-creation is disabled"):
        await service.authenticate_oidc_identity(
            FakeSession(),
            OIDCIdentity(
                subject="user_123",
                email="member@example.com",
                first_name="Member",
                last_name="User",
                issuer="https://issuer.example.com",
            ),
            auto_create_users=False,
            superuser_emails=[],
        )


@pytest.mark.asyncio
async def test_oidc_auth_rejects_inactive_subject_identity(monkeypatch) -> None:
    user = User(email="member@example.com", is_active=False)
    user.id = uuid4()
    identity = UserExternalIdentity(
        user_id=user.id,
        provider=service.oidc_identity_provider_key("https://issuer.example.com"),
        subject="user_123",
        email="member@example.com",
    )
    identity.user = user

    async def existing_identity(*args, **kwargs):
        return identity

    monkeypatch.setattr(service.repository, "get_external_identity", existing_identity)

    with pytest.raises(OIDCAuthenticationError, match="inactive"):
        await service.authenticate_oidc_identity(
            FakeSession(),
            OIDCIdentity(
                subject="user_123",
                email="member@example.com",
                first_name="Member",
                last_name="User",
                issuer="https://issuer.example.com",
            ),
            auto_create_users=True,
            superuser_emails=[],
        )


@pytest.mark.asyncio
async def test_first_oidc_login_preserves_legacy_identity_roles_and_api_tokens(monkeypatch) -> None:
    user = User(
        email="member@example.com",
        first_name="Member",
        last_name="User",
        is_active=True,
        is_superuser=True,
        is_global_moderator=True,
    )
    user.id = uuid4()
    legacy_identity = UserExternalIdentity(
        user_id=user.id,
        provider="clerk",
        subject="legacy-subject",
        email=user.email,
    )
    api_token = UserAPIToken(
        user_id=user.id,
        name="Automation",
        description="",
        token_prefix="existing",
        token_hash="existing-hash",
        scopes=["catalog:read"],
        organization_ids=[],
        is_active=True,
    )

    async def missing_oidc_identity(_session, provider, subject):
        assert provider == service.oidc_identity_provider_key("https://issuer.example.com")
        assert subject == "oidc-subject"
        return None

    async def existing_user(_session, email, *, for_update=False):
        assert email == user.email
        assert for_update is True
        return user

    async def no_oidc_identity_for_user(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_external_identity", missing_oidc_identity)
    monkeypatch.setattr(service.repository, "get_user_by_email", existing_user)
    monkeypatch.setattr(
        service.repository,
        "get_user_external_identity_for_provider",
        no_oidc_identity_for_user,
    )
    session = FakeSession()

    result = await service.authenticate_oidc_identity(
        session,
        OIDCIdentity(
            email=user.email,
            first_name="Member",
            last_name="User",
            subject="oidc-subject",
            issuer="https://issuer.example.com",
        ),
        auto_create_users=True,
        superuser_emails=[],
    )

    new_identities = [item for item in session.added if isinstance(item, UserExternalIdentity)]
    assert result is user
    assert user.is_superuser is True
    assert user.is_global_moderator is True
    assert legacy_identity.provider == "clerk"
    assert api_token.token_hash == "existing-hash"
    assert new_identities[0].provider == service.oidc_identity_provider_key(
        "https://issuer.example.com"
    )


@pytest.mark.asyncio
async def test_bootstrap_rejects_second_user(monkeypatch) -> None:
    async def count_users(*args, **kwargs):
        return 1

    monkeypatch.setattr(service.repository, "count_users", count_users)

    with pytest.raises(BootstrapUserExistsError):
        await service.bootstrap_superuser(FakeSession(), user_payload())


@pytest.mark.asyncio
async def test_authenticate_local_user_rejects_bad_password(monkeypatch) -> None:
    async def missing_user(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_user_by_email", missing_user)
    user = await service.create_user(FakeSession(), user_payload(), is_superuser=True)

    async def existing_user(*args, **kwargs):
        return user

    monkeypatch.setattr(service.repository, "get_user_by_email", existing_user)

    with pytest.raises(InvalidLoginError):
        await service.authenticate_local_user(
            FakeSession(),
            LoginRequest(email="admin@example.com", password="wrong-password"),
        )


@pytest.mark.asyncio
async def test_update_user_admin_flags_sets_global_roles(monkeypatch) -> None:
    actor = User(email="admin@example.com", is_superuser=True)
    actor.id = uuid4()
    target = User(email="reviewer@example.com")
    target.id = uuid4()

    async def get_user(*args, **kwargs):
        return target

    monkeypatch.setattr(service.repository, "get_user_by_id", get_user)

    user = await service.update_user_admin_flags(
        FakeSession(),
        actor,
        target.id,
        UserAdminUpdate(isGlobalModerator=True, isGlobalPartnerManager=True),
    )

    assert user.is_global_moderator is True
    assert user.is_global_partner_manager is True


@pytest.mark.asyncio
async def test_update_user_admin_flags_rejects_self_superuser_removal(monkeypatch) -> None:
    actor = User(email="admin@example.com", is_superuser=True)
    actor.id = uuid4()

    async def get_user(*args, **kwargs):
        return actor

    monkeypatch.setattr(service.repository, "get_user_by_id", get_user)

    with pytest.raises(InvalidUserRoleUpdateError):
        await service.update_user_admin_flags(
            FakeSession(),
            actor,
            actor.id,
            UserAdminUpdate(isSuperuser=False),
        )


@pytest.mark.asyncio
async def test_create_user_api_token_defaults_to_submission_scopes(monkeypatch) -> None:
    user = User(email="admin@example.com")
    user.id = uuid4()

    async def get_user(*args, **kwargs):
        return user

    monkeypatch.setattr(service.repository, "get_user_by_id", get_user)

    record, token = await service.create_user_api_token(
        FakeSession(),
        user.id,
        UserAPITokenCreate(name="Automation"),
    )

    assert token.startswith("wardn_hub_")
    assert record.scopes == ["catalog:read", "submissions:read", "submissions:write"]


@pytest.mark.asyncio
async def test_create_user_api_token_deduplicates_custom_scopes(monkeypatch) -> None:
    user = User(email="admin@example.com")
    user.id = uuid4()

    async def get_user(*args, **kwargs):
        return user

    monkeypatch.setattr(service.repository, "get_user_by_id", get_user)

    record, _token = await service.create_user_api_token(
        FakeSession(),
        user.id,
        UserAPITokenCreate(
            name="Catalog",
            scopes=["catalog:read", "catalog:read", "submissions:read"],
        ),
    )

    assert record.scopes == ["catalog:read", "submissions:read"]


@pytest.mark.asyncio
async def test_create_user_api_token_rejects_admin_scope_for_regular_user(monkeypatch) -> None:
    user = User(email="user@example.com")
    user.id = uuid4()

    async def get_user(*args, **kwargs):
        return user

    monkeypatch.setattr(service.repository, "get_user_by_id", get_user)

    with pytest.raises(InvalidAPITokenScopeError):
        await service.create_user_api_token(
            FakeSession(),
            user.id,
            UserAPITokenCreate(name="Scorer", scopes=["registry:score"]),
        )


@pytest.mark.asyncio
async def test_create_user_api_token_allows_admin_scope_for_superuser(monkeypatch) -> None:
    user = User(email="admin@example.com", is_superuser=True)
    user.id = uuid4()

    async def get_user(*args, **kwargs):
        return user

    monkeypatch.setattr(service.repository, "get_user_by_id", get_user)

    record, _token = await service.create_user_api_token(
        FakeSession(),
        user.id,
        UserAPITokenCreate(name="Scorer", scopes=["registry:score"]),
    )

    assert record.scopes == ["registry:score"]


@pytest.mark.asyncio
async def test_create_user_api_token_allows_moderator_scope(
    monkeypatch,
) -> None:
    user = User(email="moderator@example.com", is_global_moderator=True)
    user.id = uuid4()

    async def get_user(*args, **kwargs):
        return user

    monkeypatch.setattr(service.repository, "get_user_by_id", get_user)

    record, _token = await service.create_user_api_token(
        FakeSession(),
        user.id,
        UserAPITokenCreate(name="Review", scopes=["submissions:moderate"]),
    )

    assert record.scopes == ["submissions:moderate"]


@pytest.mark.asyncio
async def test_update_user_api_token_rejects_admin_scope_for_regular_user(monkeypatch) -> None:
    user = User(email="user@example.com")
    user.id = uuid4()
    token = UserAPIToken(
        user_id=user.id,
        name="Automation",
        description="",
        token_prefix="wardn",
        token_hash="hash",
        scopes=["catalog:read"],
        organization_ids=[],
        is_active=True,
    )
    token.id = uuid4()

    async def get_user(*args, **kwargs):
        return user

    async def get_token(*args, **kwargs):
        return token

    monkeypatch.setattr(service.repository, "get_user_by_id", get_user)
    monkeypatch.setattr(service.repository, "get_user_api_token_by_id", get_token)

    with pytest.raises(InvalidAPITokenScopeError):
        await service.update_user_api_token(
            FakeSession(),
            user.id,
            token.id,
            UserAPITokenUpdate(scopes=["registry:score"]),
        )

    assert token.scopes == ["catalog:read"]


@pytest.mark.asyncio
async def test_rotate_user_api_token_replaces_secret(monkeypatch) -> None:
    user_id = uuid4()
    token = UserAPIToken(
        user_id=user_id,
        name="Automation",
        description="",
        token_prefix="oldprefix",
        token_hash="oldhash",
        scopes=["catalog:read"],
        organization_ids=[],
        is_active=True,
        last_used_at=datetime(2026, 6, 23, tzinfo=UTC),
    )
    token.id = uuid4()

    async def get_token(*args, **kwargs):
        return token

    monkeypatch.setattr(service.repository, "get_user_api_token_by_id", get_token)

    rotated, plaintext = await service.rotate_user_api_token(FakeSession(), user_id, token.id)

    assert rotated is token
    assert plaintext.startswith("wardn_hub_")
    assert token.token_prefix != "oldprefix"
    assert token.token_hash != "oldhash"
    assert token.last_used_at is None
    assert verify_api_token(plaintext, token.token_hash)


@pytest.mark.asyncio
async def test_rotate_user_api_token_raises_for_missing_token(monkeypatch) -> None:
    async def missing_token(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_user_api_token_by_id", missing_token)

    with pytest.raises(service.UserAPITokenNotFoundError):
        await service.rotate_user_api_token(FakeSession(), uuid4(), uuid4())
