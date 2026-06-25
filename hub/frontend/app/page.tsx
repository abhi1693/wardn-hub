"use client";

import Link from "next/link";
import {
  Eye,
  FileCheck2,
  History,
  LogIn,
  Server,
  UserPlus,
} from "lucide-react";
import { useEffect, useState } from "react";

import { ServerCard } from "@/components/server-card";
import { HeaderUserMenu, SiteHeader } from "@/components/site-header";
import {
  HubApiError,
  currentUser,
  listAuditEvents,
  listPublishedServers,
  listSubmissions,
  logout,
  rejectSubmission,
  setApiToken,
  signOutExternalAuth,
  submissionAction,
} from "@/lib/api/hub";
import type {
  AuditEventRead,
  RegistryServerRead,
  SubmissionRead,
  UserRead,
} from "@/lib/api/generated/model";

type Section = "browse" | "submissions" | "audit";
type LoadState = "idle" | "loading" | "ready" | "error" | "auth";
type ShellNavItem = {
  href?: string;
  id?: Section;
  label: string;
};

const publicNavItems: ShellNavItem[] = [
  { id: "browse", label: "Explore" },
  { href: "/categories", label: "Categories" },
  { href: "/users", label: "Users" },
];

const protectedNavItems: ShellNavItem[] = [
  { id: "submissions", label: "Submissions" },
];

const adminSections = new Set<Section>(["submissions", "audit"]);

function isAdminUser(user: UserRead | null) {
  return Boolean(
    user?.is_superuser || user?.is_global_moderator || user?.is_global_partner_manager,
  );
}

function canReviewSubmissions(user: UserRead | null) {
  return Boolean(user?.is_superuser || user?.is_global_moderator);
}

function canAccessAudit(user: UserRead | null) {
  return Boolean(user?.is_superuser);
}

function canManagePartners(user: UserRead | null) {
  return Boolean(user?.is_superuser || user?.is_global_partner_manager);
}

function canAccessSection(user: UserRead | null, section: Section) {
  if (section === "audit") return canAccessAudit(user);
  if (section === "submissions") return isAdminUser(user);
  return true;
}

function canPublishSubmissions(user: UserRead | null) {
  return Boolean(user?.is_superuser);
}

function canMutateSubmission(user: UserRead | null, submission: SubmissionRead) {
  return Boolean(user?.is_superuser || submission.submitterUserId === user?.id);
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
  user,
  onSectionChange,
  onLogin,
  onRegister,
  onLogout,
  children,
}: {
  section: Section;
  isAuthenticated: boolean;
  isAdmin: boolean;
  user: UserRead | null;
  onSectionChange: (section: Section) => void;
  onLogin: () => void;
  onRegister: () => void;
  onLogout: () => void;
  children: React.ReactNode;
}) {
  const navItems = [
    ...publicNavItems,
    ...(isAdmin ? protectedNavItems : []),
    ...(canManagePartners(user) ? [{ href: "/partners", label: "Partners" }] : []),
    ...(canAccessAudit(user) ? [{ id: "audit" as const, label: "Audit" }] : []),
  ];

  return (
    <main className="site-shell">
      <SiteHeader
        brandOnClick={() => onSectionChange("browse")}
        items={navItems.map((item) => {
          const sectionId = item.id;
          return {
            active: sectionId ? section === sectionId : undefined,
            href: item.href,
            label: item.label,
            onClick: sectionId ? () => onSectionChange(sectionId) : undefined,
          };
        })}
        actions={
          isAuthenticated ? (
            <HeaderUserMenu onLogout={onLogout} user={user} />
          ) : (
            <>
              <button className="site-nav-cta" onClick={onLogin} type="button">
                <LogIn size={15} />
                Sign in
              </button>
              <button className="site-action-link" onClick={onRegister} type="button">
                <UserPlus size={16} />
                Create account
              </button>
            </>
          )
        }
      />
      <section className="workspace">
        {children}
      </section>
    </main>
  );
}

function BrowseView() {
  const [servers, setServers] = useState<RegistryServerRead[]>([]);
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState("");

  async function refresh() {
    setState("loading");
    setError("");
    try {
      const response = await listPublishedServers({ limit: 60 });
      setServers(response.servers);
      setState("ready");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load registry.");
      setState(statusFromError(caught));
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
      {state === "ready" && servers.length === 0 && (
        <div className="server-grid">
          <article className="server-card empty-server-card">
            <span className="server-card-head">
              <span className="server-card-icon">
                <Server size={22} />
              </span>
              <span>
                <strong>No MCP servers published yet</strong>
                <small>Registry</small>
              </span>
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
            <ServerCard key={server.id} server={server} />
          ))}
        </div>
      )}
    </div>
  );
}

function SubmissionsView({ user }: { user: UserRead | null }) {
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
    action: "submit" | "withdraw" | "approve" | "approve_publish" | "publish" | "reject",
  ) {
    const message =
      action === "reject" ? window.prompt("Rejection message", submission.rejectionMessage) : "";
    if (action === "reject" && !message) return;
    setBusyId(submission.id);
    setNotice("");
    try {
      if (action === "reject") {
        await rejectSubmission(submission.id, { message: message ?? "" });
      } else if (action === "approve_publish") {
        const approved = await submissionAction(submission.id, "approve");
        await submissionAction(approved.id, "publish");
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
                <Link className="small-button" href={`/submissions/${submission.id}`}>
                  <Eye size={14} />
                  Details
                </Link>
                {canMutateSubmission(user, submission) &&
                (submission.status === "draft" || submission.status === "rejected") ? (
                  <ActionButton onClick={() => void mutateSubmission(submission, "submit")}>
                    Submit
                  </ActionButton>
                ) : null}
                {submission.status === "submitted" ? (
                  <>
                    {canReviewSubmissions(user) ? (
                      <>
                        <ActionButton
                          onClick={() =>
                            void mutateSubmission(
                              submission,
                              canPublishSubmissions(user) ? "approve_publish" : "approve",
                            )
                          }
                        >
                          {canPublishSubmissions(user) ? "Approve & publish" : "Approve"}
                        </ActionButton>
                        <ActionButton onClick={() => void mutateSubmission(submission, "reject")}>
                          Reject
                        </ActionButton>
                      </>
                    ) : null}
                    {canMutateSubmission(user, submission) ? (
                      <ActionButton onClick={() => void mutateSubmission(submission, "withdraw")}>
                        Withdraw
                      </ActionButton>
                    ) : null}
                  </>
                ) : null}
                {canPublishSubmissions(user) && submission.status === "approved" ? (
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
        if (isSection(nextSection) && canAccessSection(response, nextSection)) {
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
    if (!canAccessSection(user, nextSection)) {
      setSection("browse");
      return;
    }
    setSection(nextSection);
  }

  async function signOut() {
    await logout().catch(() => undefined);
    await signOutExternalAuth({ redirectUrl: "/" });
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
      user={user}
    >
      {section === "browse" && <BrowseView />}
      {isAdmin && section === "submissions" && <SubmissionsView user={user} />}
      {canAccessAudit(user) && section === "audit" && <AuditView />}
    </AppShell>
  );
}

function isSection(value: string | null): value is Section {
  return ["browse", "submissions", "audit"].includes(value ?? "");
}
