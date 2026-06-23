"use client";

import {
  Building2,
  Database,
  FileCheck2,
  History,
  LogIn,
  Pencil,
  Plus,
  Server,
  Trash2,
  UserPlus,
} from "lucide-react";
import { useEffect, useState } from "react";

import {
  HubApiError,
  createPartnerSupport,
  currentUser,
  deleteServer,
  listAuditEvents,
  listPartnerOrganizations,
  listPartnerSupport,
  listServers,
  listSubmissions,
  logout,
  rejectSubmission,
  setApiToken,
  submissionAction,
  updatePartnerOrganization,
} from "@/lib/api/hub";
import type {
  AuditEventRead,
  PartnerOrganizationRead,
  PartnerServerSupportRead,
  RegistryServerRead,
  SubmissionRead,
  UserRead,
} from "@/lib/api/generated/model";

type Section = "browse" | "submissions" | "partners" | "audit";
type LoadState = "idle" | "loading" | "ready" | "error" | "auth";
type SupportLevel = "official" | "verified" | "compatible" | "deprecated";

const publicNavItems: Array<{ id: Section; label: string; icon: typeof Server }> = [
  { id: "browse", label: "Home", icon: Server },
];

const protectedNavItems: Array<{ id: Section; label: string; icon: typeof Server }> = [
  { id: "submissions", label: "Submissions", icon: FileCheck2 },
  { id: "partners", label: "Partners", icon: Building2 },
  { id: "audit", label: "Audit", icon: History },
];

const adminSections = new Set<Section>(["submissions", "partners", "audit"]);

function isAdminUser(user: UserRead | null) {
  return Boolean(
    user?.is_superuser || user?.is_global_moderator || user?.is_global_partner_manager,
  );
}

function statusFromError(error: unknown): LoadState {
  return error instanceof HubApiError && error.status === 401 ? "auth" : "error";
}

function formatDate(value?: string | null) {
  if (!value) return "";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function toneFor(value: string) {
  if (["active", "verified", "approved", "published", "official"].includes(value)) {
    return "success";
  }
  if (["pending", "submitted", "compatible"].includes(value)) return "pending";
  if (["failed", "rejected", "suspended", "quarantined"].includes(value)) return "danger";
  return "neutral";
}

function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: string }) {
  return <span className={`pill tone-${tone}`}>{children}</span>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <div className="empty-title">{title}</div>
      <div className="empty-detail">{detail}</div>
    </div>
  );
}

function ProtectedState({ state, error }: { state: LoadState; error: string }) {
  if (state === "loading") return <EmptyState title="Loading" detail="Fetching current data." />;
  if (state === "auth") {
    return <EmptyState title="Authentication required" detail="Protected records are hidden." />;
  }
  if (state === "error") return <EmptyState title="Request failed" detail={error} />;
  return null;
}

function ActionButton({
  children,
  onClick,
}: {
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button className="small-button" onClick={onClick} type="button">
      {children}
    </button>
  );
}

function AppShell({
  section,
  isAuthenticated,
  isAdmin,
  onSectionChange,
  onLogin,
  onRegister,
  onLogout,
  children,
}: {
  section: Section;
  isAuthenticated: boolean;
  isAdmin: boolean;
  onSectionChange: (section: Section) => void;
  onLogin: () => void;
  onRegister: () => void;
  onLogout: () => void;
  children: React.ReactNode;
}) {
  const navItems = isAdmin ? [...publicNavItems, ...protectedNavItems] : publicNavItems;

  return (
    <main className="site-shell">
      <header className="site-header">
        <button className="brand-button" onClick={() => onSectionChange("browse")} type="button">
          <Database size={18} />
          <span>Wardn Hub</span>
        </button>
        <nav className="site-nav" aria-label="Primary">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={`site-nav-item ${section === item.id ? "active" : ""}`}
                key={item.id}
                onClick={() => onSectionChange(item.id)}
                type="button"
              >
                <Icon size={17} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="site-actions">
          {isAuthenticated ? (
            <>
              <button
                className="text-button"
                onClick={() => {
                  window.location.href = "/submissions";
                }}
                type="button"
              >
                <FileCheck2 size={16} />
                My submissions
              </button>
              <button
                className="text-button"
                onClick={() => {
                  window.location.href = "/submit";
                }}
                type="button"
              >
                <Plus size={16} />
                Submit server
              </button>
              <button className="small-button" onClick={onLogout} type="button">
                Sign out
              </button>
            </>
          ) : (
            <>
              <button className="small-button" onClick={onLogin} type="button">
                <LogIn size={15} />
                Sign in
              </button>
              <button className="text-button" onClick={onRegister} type="button">
                <UserPlus size={16} />
                Create account
              </button>
            </>
          )}
        </div>
      </header>
      <section className="workspace">
        {children}
      </section>
    </main>
  );
}

function serverSubmitUrl(serverName: string, version: string) {
  const params = new URLSearchParams({ server: serverName, version });
  return `/submit?${params}`;
}

function BrowseView({ isAdmin }: { isAdmin: boolean }) {
  const [servers, setServers] = useState<RegistryServerRead[]>([]);
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busyServer, setBusyServer] = useState("");

  async function refresh() {
    setState("loading");
    setError("");
    try {
      const response = await listServers({ limit: 60 });
      setServers(response.servers);
      setState("ready");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load registry.");
      setState(statusFromError(caught));
    }
  }

  async function deleteMcpServer(server: RegistryServerRead) {
    const isConfirmed = window.confirm(
      `Delete ${server.name} and all published versions? This cannot be undone from the UI.`,
    );
    if (!isConfirmed) return;

    setBusyServer(server.name);
    setNotice("");
    setError("");
    try {
      await deleteServer(server.name);
      setNotice(`${server.name} deleted.`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to delete server.");
      setState(statusFromError(caught));
    } finally {
      setBusyServer("");
    }
  }

  useEffect(() => {
    const timeoutId = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timeoutId);
  }, []);

  return (
    <div className="home-view simple-home">
      {state === "loading" && <EmptyState title="Loading" detail="Fetching MCP servers." />}
      {state === "error" && <EmptyState title="Registry unavailable" detail={error} />}
      {notice && <div className="notice">{notice}</div>}
      {state === "ready" && servers.length === 0 && (
        <div className="server-grid">
          <article className="server-card empty-server-card">
            <span className="server-card-head">
              <span>
                <strong>No MCP servers published yet</strong>
                <small>Published servers will appear here as cards.</small>
              </span>
              <Pill tone="neutral">empty</Pill>
            </span>
            <span className="server-card-description">
              Once submissions are approved and published, this page will show one card per MCP
              server.
            </span>
          </article>
        </div>
      )}
      {servers.length > 0 && (
        <div className="server-grid">
          {servers.map((server) => (
            <article className="server-card" key={server.id}>
              <span className="server-card-head">
                <span>
                  <strong>{server.title || server.name}</strong>
                  <small>{server.name}</small>
                </span>
                <span className="server-card-status">
                  <Pill tone={toneFor(server.status)}>{server.status}</Pill>
                  {isAdmin ? (
                    <span className="server-card-actions">
                      {server.latestVersion?.version ? (
                        <button
                          aria-label={`Edit ${server.name}`}
                          className="icon-button"
                          onClick={() => {
                            window.location.href = serverSubmitUrl(
                              server.name,
                              server.latestVersion?.version ?? "",
                            );
                          }}
                          title="Edit latest version"
                          type="button"
                        >
                          <Pencil size={16} />
                        </button>
                      ) : null}
                      <button
                        aria-label={`Add version for ${server.name}`}
                        className="icon-button"
                        onClick={() => {
                          window.location.href = serverSubmitUrl(server.name, "new");
                        }}
                        title="Add version"
                        type="button"
                      >
                        <Plus size={16} />
                      </button>
                      <button
                        aria-label={`Delete ${server.name}`}
                        className="icon-button danger"
                        disabled={busyServer === server.name}
                        onClick={() => void deleteMcpServer(server)}
                        title="Delete server and all versions"
                        type="button"
                      >
                        <Trash2 size={16} />
                      </button>
                    </span>
                  ) : null}
                </span>
              </span>
              <span className="server-card-description">{server.description}</span>
              <span className="pill-stack">
                {(server.categories ?? []).slice(0, 2).map((item) => (
                  <Pill key={item.slug} tone="neutral">
                    {item.name}
                  </Pill>
                ))}
                {(server.partnerSupport ?? []).slice(0, 2).map((support) => (
                  <Pill key={`${support.organization.id}-${support.supportLevel}`} tone="success">
                    {support.supportLevel}
                  </Pill>
                ))}
                {server.latestVersion?.version && (
                  <Pill tone="neutral">{server.latestVersion.version}</Pill>
                )}
                <Pill tone="neutral">{formatDate(server.updatedAt)}</Pill>
              </span>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function SubmissionsView() {
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [submissions, setSubmissions] = useState<SubmissionRead[]>([]);
  const [busyId, setBusyId] = useState("");
  const [notice, setNotice] = useState("");

  async function refresh() {
    setState("loading");
    setError("");
    return listSubmissions()
      .then((response) => {
        setSubmissions(response.submissions);
        setState("ready");
      })
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : "Unable to load submissions.");
        setState(statusFromError(caught));
      });
  }

  async function mutateSubmission(
    submission: SubmissionRead,
    action: "submit" | "withdraw" | "approve" | "publish" | "reject",
  ) {
    const message =
      action === "reject" ? window.prompt("Rejection message", submission.rejectionMessage) : "";
    if (action === "reject" && !message) return;
    setBusyId(submission.id);
    setNotice("");
    try {
      if (action === "reject") {
        await rejectSubmission(submission.id, { message: message ?? "" });
      } else {
        await submissionAction(submission.id, action);
      }
      setNotice(`${action} completed for ${submission.name}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Action failed.");
      setState(statusFromError(caught));
    } finally {
      setBusyId("");
    }
  }

  useEffect(() => {
    const timeoutId = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timeoutId);
  }, []);

  return (
    <DataView title="Submission queue" eyebrow="Moderation" icon={FileCheck2}>
      <ProtectedState state={state} error={error} />
      {notice && <div className="notice">{notice}</div>}
      {state === "ready" && (
        <div className="records">
          {submissions.length === 0 && <EmptyState title="No submissions" detail="Queue is empty." />}
          {submissions.map((submission) => (
            <div className="record-row" key={submission.id}>
              <div>
                <strong>{submission.name}</strong>
                <small>{submission.version} · {submission.submissionType}</small>
              </div>
              <Pill tone={toneFor(submission.status)}>{submission.status}</Pill>
              <div className="action-strip">
                {submission.status === "draft" || submission.status === "rejected" ? (
                  <ActionButton onClick={() => void mutateSubmission(submission, "submit")}>
                    Submit
                  </ActionButton>
                ) : null}
                {submission.status === "submitted" ? (
                  <>
                    <ActionButton onClick={() => void mutateSubmission(submission, "approve")}>
                      Approve
                    </ActionButton>
                    <ActionButton onClick={() => void mutateSubmission(submission, "reject")}>
                      Reject
                    </ActionButton>
                    <ActionButton onClick={() => void mutateSubmission(submission, "withdraw")}>
                      Withdraw
                    </ActionButton>
                  </>
                ) : null}
                {submission.status === "approved" ? (
                  <ActionButton onClick={() => void mutateSubmission(submission, "publish")}>
                    Publish
                  </ActionButton>
                ) : null}
                {busyId === submission.id && <span className="muted">Working</span>}
                <span>{formatDate(submission.updatedAt)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </DataView>
  );
}

function PartnersView() {
  const [state, setState] = useState<LoadState>("loading");
  const [supportState, setSupportState] = useState<LoadState>("idle");
  const [error, setError] = useState("");
  const [partners, setPartners] = useState<PartnerOrganizationRead[]>([]);
  const [selected, setSelected] = useState("");
  const [support, setSupport] = useState<PartnerServerSupportRead[]>([]);
  const [supportServer, setSupportServer] = useState("");
  const [supportLevel, setSupportLevel] = useState<SupportLevel>("compatible");
  const [notice, setNotice] = useState("");

  async function refreshPartners() {
    setState("loading");
    setError("");
    return listPartnerOrganizations()
      .then((response) => {
        setPartners(response.organizations);
        setSelected((current) => current || response.organizations[0]?.id || "");
        setState("ready");
      })
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : "Unable to load partners.");
        setState(statusFromError(caught));
      });
  }

  async function refreshSupport(organizationId: string) {
    setSupportState("loading");
    return listPartnerSupport(organizationId)
      .then((response) => {
        setSupport(response.support);
        setSupportState("ready");
      })
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : "Unable to load support records.");
        setSupportState(statusFromError(caught));
      });
  }

  async function activateSelectedPartner() {
    if (!selected) return;
    setNotice("");
    try {
      await updatePartnerOrganization(selected, {
        isPartner: true,
        partnerStatus: "active",
        partnerTier: "verified",
      });
      setNotice("Partner metadata updated.");
      await refreshPartners();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to update partner.");
      setState(statusFromError(caught));
    }
  }

  async function createSupport(event: React.FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setNotice("");
    try {
      await createPartnerSupport(selected, {
        serverName: supportServer,
        supportLevel,
        supportStatus: "active",
      });
      setSupportServer("");
      setNotice("Server support record created.");
      await refreshSupport(selected);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create support record.");
      setSupportState(statusFromError(caught));
    }
  }

  useEffect(() => {
    const timeoutId = window.setTimeout(() => void refreshPartners(), 0);
    return () => window.clearTimeout(timeoutId);
  }, []);

  useEffect(() => {
    if (!selected) return;
    const timeoutId = window.setTimeout(() => void refreshSupport(selected), 0);
    return () => window.clearTimeout(timeoutId);
  }, [selected]);

  return (
    <DataView title="Partner organizations" eyebrow="Support Metadata" icon={Building2}>
      <ProtectedState state={state} error={error} />
      {notice && <div className="notice">{notice}</div>}
      {state === "ready" && (
        <div className="split-layout">
          <div className="records">
            {partners.length === 0 && <EmptyState title="No partners" detail="No active partners." />}
            {partners.map((partner) => (
              <button
                className={`record-row selectable ${selected === partner.id ? "selected" : ""}`}
                key={partner.id}
                onClick={() => setSelected(partner.id)}
                type="button"
              >
                <div>
                  <strong>{partner.name}</strong>
                  <small>{partner.slug}</small>
                </div>
                <Pill tone={toneFor(partner.partnerStatus)}>{partner.partnerStatus}</Pill>
                <Pill tone={toneFor(partner.partnerTier)}>{partner.partnerTier}</Pill>
              </button>
            ))}
          </div>
          <div className="side-surface">
            <div className="side-header">
              <h2>Server support</h2>
              <ActionButton onClick={() => void activateSelectedPartner()}>Mark active</ActionButton>
            </div>
            <form className="stacked-form" onSubmit={(event) => void createSupport(event)}>
              <input
                onChange={(event) => setSupportServer(event.target.value)}
                placeholder="io.github.example/weather"
                required
                value={supportServer}
              />
              <select
                onChange={(event) => setSupportLevel(event.target.value as SupportLevel)}
                value={supportLevel}
              >
                <option value="compatible">compatible</option>
                <option value="verified">verified</option>
                <option value="official">official</option>
                <option value="deprecated">deprecated</option>
              </select>
              <button className="text-button" type="submit">
                Add support
              </button>
            </form>
            <ProtectedState state={supportState} error={error} />
            {supportState === "ready" && support.length === 0 && (
              <EmptyState title="No support records" detail="No mapped servers." />
            )}
            {support.map((record) => (
              <div className="support-row" key={record.id}>
                <span>{record.serverName}</span>
                <Pill tone={toneFor(record.supportLevel)}>{record.supportLevel}</Pill>
              </div>
            ))}
          </div>
        </div>
      )}
    </DataView>
  );
}

function AuditView() {
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [events, setEvents] = useState<AuditEventRead[]>([]);

  useEffect(() => {
    listAuditEvents()
      .then((response) => {
        setEvents(response.events);
        setState("ready");
      })
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : "Unable to load audit events.");
        setState(statusFromError(caught));
      });
  }, []);

  return (
    <DataView title="Audit events" eyebrow="Operations" icon={History}>
      <ProtectedState state={state} error={error} />
      {state === "ready" && (
        <div className="records">
          {events.length === 0 && <EmptyState title="No events" detail="Audit stream is empty." />}
          {events.map((event) => (
            <div className="record-row" key={event.id}>
              <div>
                <strong>{event.eventType}</strong>
                <small>{event.subjectType} · {event.subjectId}</small>
              </div>
              <span>{formatDate(event.createdAt)}</span>
            </div>
          ))}
        </div>
      )}
    </DataView>
  );
}

function DataView({
  title,
  eyebrow,
  icon: Icon,
  children,
}: {
  title: string;
  eyebrow: string;
  icon: typeof Server;
  children: React.ReactNode;
}) {
  return (
    <div className="view">
      <header className="view-header">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
        </div>
        <div className="header-icon">
          <Icon size={18} />
        </div>
      </header>
      <div className="table-surface roomy">{children}</div>
    </div>
  );
}

export default function Home() {
  const [section, setSection] = useState<Section>("browse");
  const [user, setUser] = useState<UserRead | null>(null);
  const isAuthenticated = user !== null;
  const isAdmin = isAdminUser(user);

  useEffect(() => {
    currentUser()
      .then((response) => {
        setUser(response);
        const nextSection = new URLSearchParams(window.location.search).get("section");
        if (isSection(nextSection) && adminSections.has(nextSection) && isAdminUser(response)) {
          setSection(nextSection);
        }
      })
      .catch(() => setUser(null));
  }, []);

  function goToAuth(mode: "login" | "register", nextSection?: Section) {
    const params = new URLSearchParams();
    if (nextSection && nextSection !== "browse") params.set("next", nextSection);
    window.location.href = `/${mode}${params.size ? `?${params}` : ""}`;
  }

  function selectSection(nextSection: Section) {
    if (adminSections.has(nextSection) && !isAuthenticated) {
      goToAuth("login", nextSection);
      return;
    }
    if (adminSections.has(nextSection) && !isAdmin) {
      setSection("browse");
      return;
    }
    setSection(nextSection);
  }

  async function signOut() {
    await logout().catch(() => undefined);
    setApiToken("");
    setUser(null);
    setSection("browse");
  }

  return (
    <AppShell
      isAdmin={isAdmin}
      isAuthenticated={isAuthenticated}
      onLogin={() => goToAuth("login")}
      onLogout={() => void signOut()}
      onRegister={() => goToAuth("register")}
      onSectionChange={selectSection}
      section={section}
    >
      {section === "browse" && <BrowseView isAdmin={isAdmin} />}
      {isAdmin && section === "submissions" && <SubmissionsView />}
      {isAdmin && section === "partners" && <PartnersView />}
      {isAdmin && section === "audit" && <AuditView />}
    </AppShell>
  );
}

function isSection(value: string | null): value is Section {
  return ["browse", "submissions", "partners", "audit"].includes(value ?? "");
}
