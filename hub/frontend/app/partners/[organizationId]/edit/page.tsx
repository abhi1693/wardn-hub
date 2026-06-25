"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { PublicHeader } from "@/components/site-header";
import {
  listOrganizationMemberships,
  listOrganizationRoles,
  listPartnerOrganizations,
  listRegistryUsers,
  type RegistryUserRead,
  currentUser,
  updatePartnerOrganization,
  updateOrganizationMembership,
  upsertOrganizationMembership,
} from "@/lib/api/hub";
import type {
  OrganizationMembershipRead,
  OrganizationRoleRead,
  PartnerOrganizationRead,
  PartnerOrganizationUpdate,
} from "@/lib/api/generated/model";

type LoadState = "loading" | "ready" | "error";
type PartnerStatus = NonNullable<PartnerOrganizationUpdate["partnerStatus"]>;
type PartnerTier = NonNullable<PartnerOrganizationUpdate["partnerTier"]>;
type PartnerSupportLevel = NonNullable<PartnerOrganizationUpdate["partnerSupportLevel"]>;

function formatDate(value?: string | null) {
  if (!value) return "Not available";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function canManagePartners(user: { is_superuser: boolean; is_global_partner_manager: boolean }) {
  return user.is_superuser || user.is_global_partner_manager;
}

export default function EditPartnerPage() {
  const params = useParams<{ organizationId?: string }>();
  const router = useRouter();
  const organizationId = params.organizationId ?? "";
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [partner, setPartner] = useState<PartnerOrganizationRead | null>(null);
  const [memberships, setMemberships] = useState<OrganizationMembershipRead[]>([]);
  const [roles, setRoles] = useState<OrganizationRoleRead[]>([]);
  const [registryUsers, setRegistryUsers] = useState<RegistryUserRead[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isAssigningMember, setIsAssigningMember] = useState(false);
  const [updatingMemberId, setUpdatingMemberId] = useState("");

  const [partnerStatus, setPartnerStatus] = useState<PartnerStatus>("active");
  const [partnerTier, setPartnerTier] = useState<PartnerTier>("verified");
  const [partnerSupportLevel, setPartnerSupportLevel] =
    useState<PartnerSupportLevel>("compatible");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [supportEmail, setSupportEmail] = useState("");

  const [memberUserId, setMemberUserId] = useState("");
  const [memberRoleSlug, setMemberRoleSlug] = useState("publisher");

  const refresh = useCallback(async () => {
    if (!organizationId) return;
    setState("loading");
    setError("");
    const user = await currentUser();
    if (!canManagePartners(user)) {
      throw new Error("Partner management requires partner manager access.");
    }
    const [
      partnerResponse,
      membershipResponse,
      roleResponse,
      userResponse,
    ] = await Promise.all([
      listPartnerOrganizations(),
      listOrganizationMemberships(organizationId),
      listOrganizationRoles(organizationId),
      listRegistryUsers().catch(() => ({ users: [] })),
    ]);
    const current = partnerResponse.organizations.find((item) => item.id === organizationId) ?? null;
    if (!current) throw new Error("Partner organization not found.");

    setPartner(current);
    setPartnerStatus(current.partnerStatus as PartnerStatus);
    setPartnerTier(current.partnerTier as PartnerTier);
    setPartnerSupportLevel(current.partnerSupportLevel);
    setWebsiteUrl(current.websiteUrl);
    setSupportEmail(current.supportEmail);
    setMemberships(membershipResponse.memberships);
    setRoles(roleResponse.roles);
    setRegistryUsers(userResponse.users);
    setMemberRoleSlug((currentRole) => {
      if (currentRole && roleResponse.roles.some((role) => role.slug === currentRole)) {
        return currentRole;
      }
      return roleResponse.roles.find((role) => role.slug === "publisher")?.slug
        ?? roleResponse.roles[0]?.slug
        ?? "";
    });
    setState("ready");
  }, [organizationId]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      refresh().catch((caught) => {
        setError(caught instanceof Error ? caught.message : "Unable to load partner.");
        setState("error");
      });
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [refresh]);

  const userById = useMemo(
    () => new Map(registryUsers.map((user) => [user.id, user])),
    [registryUsers],
  );
  const sortedMemberships = useMemo(
    () => [...memberships].sort((left, right) => Number(right.isActive) - Number(left.isActive)),
    [memberships],
  );

  async function savePartner(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setError("");
    setNotice("");
    try {
      const updated = await updatePartnerOrganization(organizationId, {
        isPartner: true,
        partnerStatus,
        partnerTier,
        partnerSupportLevel,
        websiteUrl: websiteUrl.trim() || null,
        supportEmail: supportEmail.trim() || null,
      });
      setPartner(updated);
      setNotice("Partner metadata saved.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save partner.");
    } finally {
      setIsSaving(false);
    }
  }

  async function deletePartner() {
    const confirmed = window.confirm(
      `Remove ${partner?.name ?? "this organization"} from partners? The organization record will remain.`,
    );
    if (!confirmed) return;

    setIsDeleting(true);
    setError("");
    setNotice("");
    try {
      await updatePartnerOrganization(organizationId, {
        isPartner: false,
        partnerStatus: "none",
      });
      router.push("/partners");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to delete partner.");
      setIsDeleting(false);
    }
  }

  async function assignMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    setIsAssigningMember(true);
    try {
      await upsertOrganizationMembership(organizationId, {
        userId: memberUserId.trim(),
        roleSlug: memberRoleSlug,
      });
      setMemberUserId("");
      setNotice("Partner user assigned.");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to assign partner user.");
    } finally {
      setIsAssigningMember(false);
    }
  }

  async function saveMember(
    membership: OrganizationMembershipRead,
    payload: { isActive: boolean; roleSlug: string },
  ) {
    setError("");
    setNotice("");
    setUpdatingMemberId(membership.userId);
    try {
      const updated = await updateOrganizationMembership(organizationId, membership.userId, payload);
      setMemberships((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setNotice("Partner user access updated.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to update partner user.");
    } finally {
      setUpdatingMemberId("");
    }
  }

  function userLabel(userId: string) {
    const user = userById.get(userId);
    if (!user) return "User";
    return user.name || user.login || user.id;
  }

  return (
    <div className="server-detail-page">
      <PublicHeader />

      <main className="server-detail-main">
        <section className="category-page-header">
          <div>
            <h1>{partner?.name ?? "Edit Partner"}</h1>
            <p>{partner ? `${partner.slug} · updated ${formatDate(partner.updatedAt)}` : "Manage partner metadata."}</p>
          </div>
          <Link className="site-action-link" href="/partners">
            Partners
          </Link>
        </section>

        {state === "loading" ? (
          <div className="empty-state">
            <div className="empty-title">Loading</div>
            <div className="empty-detail">Fetching partner details.</div>
          </div>
        ) : null}

        {state === "error" ? (
          <div className="empty-state">
            <div className="empty-title">Partner unavailable</div>
            <div className="empty-detail">{error}</div>
          </div>
        ) : null}

        {state === "ready" ? (
          <div className="partner-edit-layout">
            <div className="partner-edit-main">
              {error ? <div className="error-banner">{error}</div> : null}
              {notice ? <div className="notice">{notice}</div> : null}

              <form className="partner-form" onSubmit={(event) => void savePartner(event)}>
                <h2>Partner Metadata</h2>
                <div className="partner-form-grid">
                  <label>
                    <span>Status</span>
                    <select
                      onChange={(event) => setPartnerStatus(event.target.value as PartnerStatus)}
                      value={partnerStatus}
                    >
                      <option value="pending">pending</option>
                      <option value="active">active</option>
                      <option value="suspended">suspended</option>
                      <option value="ended">ended</option>
                    </select>
                  </label>
                  <label>
                    <span>Tier</span>
                    <select
                      onChange={(event) => setPartnerTier(event.target.value as PartnerTier)}
                      value={partnerTier}
                    >
                      <option value="official">official</option>
                      <option value="supported">supported</option>
                      <option value="verified">verified</option>
                      <option value="community">community</option>
                    </select>
                  </label>
                  <label>
                    <span>Support Level</span>
                    <select
                      onChange={(event) =>
                        setPartnerSupportLevel(event.target.value as PartnerSupportLevel)
                      }
                      value={partnerSupportLevel}
                    >
                      <option value="official">official</option>
                      <option value="verified">verified</option>
                      <option value="compatible">compatible</option>
                      <option value="deprecated">deprecated</option>
                    </select>
                  </label>
                  <label>
                    <span>Website URL</span>
                    <input onChange={(event) => setWebsiteUrl(event.target.value)} value={websiteUrl} />
                  </label>
                  <label>
                    <span>Support Email</span>
                    <input
                      onChange={(event) => setSupportEmail(event.target.value)}
                      type="email"
                      value={supportEmail}
                    />
                  </label>
                </div>
                <div className="partner-form-actions">
                  <button className="site-nav-cta" disabled={isSaving} type="submit">
                    {isSaving ? "Saving" : "Save Partner"}
                  </button>
                </div>
              </form>

              <section className="partner-form">
                <h2>Partner Users</h2>
                <form className="partner-member-form" onSubmit={(event) => void assignMember(event)}>
                  <label>
                    <span>User</span>
                    <select
                      disabled={registryUsers.length === 0}
                      onChange={(event) => setMemberUserId(event.target.value)}
                      required
                      value={memberUserId}
                    >
                      <option value="">
                        {registryUsers.length === 0 ? "No users available" : "Select user"}
                      </option>
                      {registryUsers.map((user) => (
                        <option
                          key={user.id}
                          value={user.id}
                        >
                          {user.name || user.login || user.id}
                          {user.login && user.name ? ` (${user.login})` : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Role</span>
                    <select
                      onChange={(event) => setMemberRoleSlug(event.target.value)}
                      required
                      value={memberRoleSlug}
                    >
                      {roles.map((role) => (
                        <option key={role.id} value={role.slug}>
                          {role.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button className="site-nav-cta" disabled={isAssigningMember} type="submit">
                    {isAssigningMember ? "Assigning" : "Assign User"}
                  </button>
                </form>

                {sortedMemberships.length === 0 ? (
                  <div className="empty-state compact">
                    <div className="empty-title">No partner users</div>
                    <div className="empty-detail">Assign users so they can manage partner servers.</div>
                  </div>
                ) : (
                  <div className="partner-member-table">
                    <div className="partner-member-table-header">
                      <span>User</span>
                      <span>Role</span>
                      <span>Status</span>
                      <span />
                    </div>
                    {sortedMemberships.map((membership) => (
                      <div className="partner-member-row" key={membership.id}>
                        <div className="partner-member-user">
                          <strong>{userLabel(membership.userId)}</strong>
                          <small>{membership.userId}</small>
                        </div>
                        <label className="partner-member-role">
                          <span>Role</span>
                          <select
                            disabled={updatingMemberId === membership.userId}
                            onChange={(event) =>
                              void saveMember(membership, {
                                isActive: membership.isActive,
                                roleSlug: event.target.value,
                              })
                            }
                            value={membership.roleSlug}
                          >
                            {roles.map((role) => (
                              <option key={role.id} value={role.slug}>
                                {role.name}
                              </option>
                            ))}
                          </select>
                        </label>
                        <div className="partner-member-status">
                          <span>Status</span>
                          <strong>{membership.isActive ? "active" : "inactive"}</strong>
                        </div>
                        <div className="partner-member-actions">
                          <button
                            className={`partner-row-action ${membership.isActive ? "danger" : ""}`}
                            disabled={updatingMemberId === membership.userId}
                            onClick={() =>
                              void saveMember(membership, {
                                isActive: !membership.isActive,
                                roleSlug: membership.roleSlug,
                              })
                            }
                            type="button"
                          >
                            {membership.isActive ? "Remove" : "Restore"}
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              <section className="partner-danger-zone">
                <div>
                  <h2>Delete Partner</h2>
                  <p>Remove this organization from partner listings. The organization record is kept.</p>
                </div>
                <button
                  className="danger-action-button"
                  disabled={isDeleting}
                  onClick={() => void deletePartner()}
                  type="button"
                >
                  {isDeleting ? "Deleting" : "Delete Partner"}
                </button>
              </section>
            </div>

          </div>
        ) : null}
      </main>
    </div>
  );
}
