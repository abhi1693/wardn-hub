"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { PublicHeader } from "@/components/site-header";
import {
  createPartnerSupport,
  listOrganizationMemberships,
  listOrganizationRoles,
  listPartnerOrganizations,
  listPartnerSupport,
  listRegistryUsers,
  type RegistryUserRead,
  currentUser,
  updatePartnerOrganization,
  updatePartnerSupport,
  updateOrganizationMembership,
  upsertOrganizationMembership,
} from "@/lib/api/hub";
import type {
  OrganizationMembershipRead,
  OrganizationRoleRead,
  PartnerOrganizationRead,
  PartnerOrganizationUpdate,
  PartnerServerSupportCreate,
  PartnerServerSupportRead,
  PartnerServerSupportUpdate,
} from "@/lib/api/generated/model";

type LoadState = "loading" | "ready" | "error";
type PartnerStatus = NonNullable<PartnerOrganizationUpdate["partnerStatus"]>;
type PartnerTier = NonNullable<PartnerOrganizationUpdate["partnerTier"]>;
type PartnerSupportLevel = NonNullable<PartnerOrganizationUpdate["partnerSupportLevel"]>;
type ServerSupportLevel = NonNullable<PartnerServerSupportCreate["supportLevel"]>;
type ServerSupportStatus = NonNullable<PartnerServerSupportCreate["supportStatus"]>;
type SupportDraft = {
  supportLevel: ServerSupportLevel;
  supportStatus: ServerSupportStatus;
  supportUrl: string;
  docsUrl: string;
  startsAt: string;
  endsAt: string;
};

function formatDate(value?: string | null) {
  if (!value) return "Not available";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function toDateTimeInputValue(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 16);
}

function fromDateTimeInputValue(value: string) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function supportDraftFromRecord(record: PartnerServerSupportRead): SupportDraft {
  return {
    supportLevel: record.supportLevel,
    supportStatus: record.supportStatus,
    supportUrl: record.supportUrl,
    docsUrl: record.docsUrl,
    startsAt: toDateTimeInputValue(record.startsAt),
    endsAt: toDateTimeInputValue(record.endsAt),
  };
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
  const [supportRecords, setSupportRecords] = useState<PartnerServerSupportRead[]>([]);
  const [supportDrafts, setSupportDrafts] = useState<Record<string, SupportDraft>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isAssigningMember, setIsAssigningMember] = useState(false);
  const [isCreatingSupport, setIsCreatingSupport] = useState(false);
  const [updatingMemberId, setUpdatingMemberId] = useState("");
  const [updatingSupportId, setUpdatingSupportId] = useState("");

  const [partnerStatus, setPartnerStatus] = useState<PartnerStatus>("active");
  const [partnerTier, setPartnerTier] = useState<PartnerTier>("verified");
  const [partnerSupportLevel, setPartnerSupportLevel] =
    useState<PartnerSupportLevel>("compatible");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [supportEmail, setSupportEmail] = useState("");

  const [memberUserId, setMemberUserId] = useState("");
  const [memberRoleSlug, setMemberRoleSlug] = useState("publisher");
  const [supportServerName, setSupportServerName] = useState("");
  const [supportLevel, setSupportLevel] = useState<ServerSupportLevel>("compatible");
  const [supportStatus, setSupportStatus] = useState<ServerSupportStatus>("pending");
  const [supportUrl, setSupportUrl] = useState("");
  const [supportDocsUrl, setSupportDocsUrl] = useState("");
  const [supportStartsAt, setSupportStartsAt] = useState("");
  const [supportEndsAt, setSupportEndsAt] = useState("");
  const [supportInternalNotes, setSupportInternalNotes] = useState("");

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
      supportResponse,
    ] = await Promise.all([
      listPartnerOrganizations(),
      listOrganizationMemberships(organizationId),
      listOrganizationRoles(organizationId),
      listRegistryUsers().catch(() => ({ users: [] })),
      listPartnerSupport(organizationId),
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
    setSupportRecords(supportResponse.support);
    setSupportDrafts(
      Object.fromEntries(
        supportResponse.support.map((record) => [record.id, supportDraftFromRecord(record)]),
      ),
    );
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
  const sortedSupportRecords = useMemo(
    () => [...supportRecords].sort((left, right) => left.serverName.localeCompare(right.serverName)),
    [supportRecords],
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

  async function createSupportRecord(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    setIsCreatingSupport(true);
    try {
      const payload: PartnerServerSupportCreate = {
        serverName: supportServerName.trim(),
        supportLevel,
        supportStatus,
        supportUrl: supportUrl.trim(),
        docsUrl: supportDocsUrl.trim(),
        startsAt: fromDateTimeInputValue(supportStartsAt),
        endsAt: fromDateTimeInputValue(supportEndsAt),
        internalNotes: supportInternalNotes.trim(),
      };
      const created = await createPartnerSupport(organizationId, payload);
      setSupportRecords((current) => [...current, created]);
      setSupportDrafts((current) => ({
        ...current,
        [created.id]: supportDraftFromRecord(created),
      }));
      setSupportServerName("");
      setSupportLevel("compatible");
      setSupportStatus("pending");
      setSupportUrl("");
      setSupportDocsUrl("");
      setSupportStartsAt("");
      setSupportEndsAt("");
      setSupportInternalNotes("");
      setNotice("Server support mapping created.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create support mapping.");
    } finally {
      setIsCreatingSupport(false);
    }
  }

  function updateSupportDraft(supportId: string, payload: Partial<SupportDraft>) {
    setSupportDrafts((current) => ({
      ...current,
      [supportId]: {
        ...current[supportId],
        ...payload,
      },
    }));
  }

  async function saveSupport(record: PartnerServerSupportRead) {
    const draft = supportDrafts[record.id];
    if (!draft) return;
    setError("");
    setNotice("");
    setUpdatingSupportId(record.id);
    try {
      const payload: PartnerServerSupportUpdate = {
        supportLevel: draft.supportLevel,
        supportStatus: draft.supportStatus,
        supportUrl: draft.supportUrl.trim() || null,
        docsUrl: draft.docsUrl.trim() || null,
        startsAt: fromDateTimeInputValue(draft.startsAt),
        endsAt: fromDateTimeInputValue(draft.endsAt),
      };
      const updated = await updatePartnerSupport(record.id, payload);
      setSupportRecords((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setSupportDrafts((current) => ({
        ...current,
        [updated.id]: supportDraftFromRecord(updated),
      }));
      setNotice("Server support mapping updated.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to update support mapping.");
    } finally {
      setUpdatingSupportId("");
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

              <section className="partner-form">
                <h2>Server Support</h2>
                <form
                  className="partner-support-create-form"
                  onSubmit={(event) => void createSupportRecord(event)}
                >
                  <label>
                    <span>Server Name</span>
                    <input
                      onChange={(event) => setSupportServerName(event.target.value)}
                      placeholder="publisher/server"
                      required
                      value={supportServerName}
                    />
                  </label>
                  <label>
                    <span>Level</span>
                    <select
                      onChange={(event) => setSupportLevel(event.target.value as ServerSupportLevel)}
                      value={supportLevel}
                    >
                      <option value="official">official</option>
                      <option value="verified">verified</option>
                      <option value="compatible">compatible</option>
                      <option value="deprecated">deprecated</option>
                    </select>
                  </label>
                  <label>
                    <span>Status</span>
                    <select
                      onChange={(event) =>
                        setSupportStatus(event.target.value as ServerSupportStatus)
                      }
                      value={supportStatus}
                    >
                      <option value="pending">pending</option>
                      <option value="active">active</option>
                      <option value="suspended">suspended</option>
                      <option value="ended">ended</option>
                    </select>
                  </label>
                  <label>
                    <span>Support URL</span>
                    <input
                      onChange={(event) => setSupportUrl(event.target.value)}
                      value={supportUrl}
                    />
                  </label>
                  <label>
                    <span>Docs URL</span>
                    <input
                      onChange={(event) => setSupportDocsUrl(event.target.value)}
                      value={supportDocsUrl}
                    />
                  </label>
                  <label>
                    <span>Starts At</span>
                    <input
                      onChange={(event) => setSupportStartsAt(event.target.value)}
                      type="datetime-local"
                      value={supportStartsAt}
                    />
                  </label>
                  <label>
                    <span>Ends At</span>
                    <input
                      onChange={(event) => setSupportEndsAt(event.target.value)}
                      type="datetime-local"
                      value={supportEndsAt}
                    />
                  </label>
                  <label className="partner-support-notes">
                    <span>Internal Notes</span>
                    <textarea
                      onChange={(event) => setSupportInternalNotes(event.target.value)}
                      rows={3}
                      value={supportInternalNotes}
                    />
                  </label>
                  <div className="partner-form-actions partner-support-actions">
                    <button className="site-nav-cta" disabled={isCreatingSupport} type="submit">
                      {isCreatingSupport ? "Creating" : "Add Support"}
                    </button>
                  </div>
                </form>

                {sortedSupportRecords.length === 0 ? (
                  <div className="empty-state compact">
                    <div className="empty-title">No server support</div>
                    <div className="empty-detail">
                      Add server mappings to show this partner support relationship in registry views.
                    </div>
                  </div>
                ) : (
                  <div className="partner-support-table">
                    <div className="partner-support-table-header">
                      <span>Server</span>
                      <span>Level</span>
                      <span>Status</span>
                      <span>URLs</span>
                      <span>Dates</span>
                      <span />
                    </div>
                    {sortedSupportRecords.map((record) => {
                      const draft = supportDrafts[record.id] ?? supportDraftFromRecord(record);
                      const isUpdating = updatingSupportId === record.id;
                      return (
                        <div className="partner-support-row" key={record.id}>
                          <div className="partner-support-server">
                            <strong>{record.serverName}</strong>
                            <small>Updated {formatDate(record.updatedAt)}</small>
                          </div>
                          <label className="partner-support-field">
                            <span>Level</span>
                            <select
                              disabled={isUpdating}
                              onChange={(event) =>
                                updateSupportDraft(record.id, {
                                  supportLevel: event.target.value as ServerSupportLevel,
                                })
                              }
                              value={draft.supportLevel}
                            >
                              <option value="official">official</option>
                              <option value="verified">verified</option>
                              <option value="compatible">compatible</option>
                              <option value="deprecated">deprecated</option>
                            </select>
                          </label>
                          <label className="partner-support-field">
                            <span>Status</span>
                            <select
                              disabled={isUpdating}
                              onChange={(event) =>
                                updateSupportDraft(record.id, {
                                  supportStatus: event.target.value as ServerSupportStatus,
                                })
                              }
                              value={draft.supportStatus}
                            >
                              <option value="pending">pending</option>
                              <option value="active">active</option>
                              <option value="suspended">suspended</option>
                              <option value="ended">ended</option>
                            </select>
                          </label>
                          <div className="partner-support-url-fields">
                            <label className="partner-support-field">
                              <span>Support URL</span>
                              <input
                                disabled={isUpdating}
                                onChange={(event) =>
                                  updateSupportDraft(record.id, { supportUrl: event.target.value })
                                }
                                value={draft.supportUrl}
                              />
                            </label>
                            <label className="partner-support-field">
                              <span>Docs URL</span>
                              <input
                                disabled={isUpdating}
                                onChange={(event) =>
                                  updateSupportDraft(record.id, { docsUrl: event.target.value })
                                }
                                value={draft.docsUrl}
                              />
                            </label>
                          </div>
                          <div className="partner-support-date-fields">
                            <label className="partner-support-field">
                              <span>Starts At</span>
                              <input
                                disabled={isUpdating}
                                onChange={(event) =>
                                  updateSupportDraft(record.id, { startsAt: event.target.value })
                                }
                                type="datetime-local"
                                value={draft.startsAt}
                              />
                            </label>
                            <label className="partner-support-field">
                              <span>Ends At</span>
                              <input
                                disabled={isUpdating}
                                onChange={(event) =>
                                  updateSupportDraft(record.id, { endsAt: event.target.value })
                                }
                                type="datetime-local"
                                value={draft.endsAt}
                              />
                            </label>
                          </div>
                          <div className="partner-support-actions-cell">
                            <button
                              className="partner-row-action"
                              disabled={isUpdating}
                              onClick={() => void saveSupport(record)}
                              type="button"
                            >
                              {isUpdating ? "Saving" : "Save"}
                            </button>
                          </div>
                        </div>
                      );
                    })}
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
