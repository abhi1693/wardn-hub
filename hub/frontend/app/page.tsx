"use client";

import {
  BadgeCheck,
  Building2,
  Database,
  FileCheck2,
  History,
  KeyRound,
  LogIn,
  RefreshCw,
  Search,
  Server,
  Settings,
  ShieldCheck,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  DEFAULT_API_BASE_URL,
  HubApiError,
  bootstrap,
  createNamespaceClaim,
  createPartnerSupport,
  getServer,
  getApiToken,
  listAuditEvents,
  listNamespaceClaims,
  listPartnerOrganizations,
  listPartnerSupport,
  listServers,
  listSubmissions,
  login,
  logout,
  namespaceDecision,
  rejectSubmission,
  revokeNamespaceClaim,
  setApiToken,
  submissionAction,
  updatePartnerOrganization,
} from "@/lib/api/hub";
import type {
  AuditEventRead,
  NamespaceClaimRead,
  PartnerOrganizationRead,
  PartnerServerSupportRead,
  RegistryServerRead,
  RegistryServerVersionRead,
  SubmissionRead,
  UserRead,
} from "@/lib/api/generated/model";

type Section = "browse" | "submissions" | "partners" | "namespaces" | "audit" | "settings";
type LoadState = "idle" | "loading" | "ready" | "error" | "auth";
type NamespaceMethod = "github" | "dns" | "http";
type SupportLevel = "official" | "verified" | "compatible" | "deprecated";

const navItems: Array<{ id: Section; label: string; icon: typeof Server }> = [
  { id: "browse", label: "Home", icon: Server },
  { id: "submissions", label: "Submissions", icon: FileCheck2 },
  { id: "partners", label: "Partners", icon: Building2 },
  { id: "namespaces", label: "Namespaces", icon: ShieldCheck },
  { id: "audit", label: "Audit", icon: History },
  { id: "settings", label: "Settings", icon: Settings },
];

const supportLevels = ["", "official", "verified", "compatible", "deprecated"];
const registryChips = [
  { label: "Featured", supportLevel: "", partnerOnly: false, search: "" },
  { label: "All", supportLevel: "", partnerOnly: false, search: "" },
  { label: "Official", supportLevel: "official", partnerOnly: false, search: "" },
  { label: "Verified", supportLevel: "verified", partnerOnly: false, search: "" },
  { label: "Search", supportLevel: "", partnerOnly: false, search: "search" },
  { label: "Development", supportLevel: "", partnerOnly: false, search: "development" },
  { label: "Database", supportLevel: "", partnerOnly: false, search: "database" },
  { label: "Cloud Service", supportLevel: "", partnerOnly: false, search: "cloud" },
  { label: "Productivity", supportLevel: "", partnerOnly: false, search: "productivity" },
  { label: "Partners", supportLevel: "", partnerOnly: true, search: "" },
];

const topicCards = [
  {
    title: "Browser Automation MCP",
    detail: "Servers for browser control, screenshots, scraping, and repeatable web tasks.",
  },
  {
    title: "RAG MCP",
    detail: "Retrieval, vector search, knowledge bases, and source-grounded workflows.",
  },
  {
    title: "OpenAPI MCP",
    detail: "Expose REST APIs, schemas, and developer docs to MCP-compatible agents.",
  },
  {
    title: "Coding Agent MCP",
    detail: "Repository context, pull requests, documentation lookup, and local tooling.",
  },
];

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
  onSectionChange,
  onOpenAuth,
  children,
}: {
  section: Section;
  onSectionChange: (section: Section) => void;
  onOpenAuth: () => void;
  children: React.ReactNode;
}) {
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
          <button className="text-button subtle" onClick={() => onSectionChange("submissions")} type="button">
            Submit
          </button>
          <button className="text-button" onClick={onOpenAuth} type="button">
            <LogIn size={16} />
            Sign in
          </button>
        </div>
      </header>
      <section className="workspace">
        {children}
      </section>
    </main>
  );
}

function AuthDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [token, setToken] = useState("");
  const [user, setUser] = useState<UserRead | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    queueMicrotask(() => setToken(getApiToken()));
  }, [open]);

  if (!open) return null;

  async function submitLogin(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      const response = await login({ email, password });
      setUser(response);
      setNotice(`Signed in as ${response.email}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Login failed.");
    }
  }

  async function submitBootstrap(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      const response = await bootstrap({
        email,
        password,
        first_name: firstName,
        last_name: lastName,
      });
      setUser(response);
      setNotice(`Bootstrapped ${response.email}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Bootstrap failed.");
    }
  }

  async function submitLogout() {
    setError("");
    setNotice("");
    try {
      await logout();
      setUser(null);
      setNotice("Signed out.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Logout failed.");
    }
  }

  function saveToken() {
    setApiToken(token);
    setNotice(token.trim() ? "Bearer token saved." : "Bearer token cleared.");
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section aria-label="Authentication" className="auth-modal">
        <header className="modal-header">
          <div>
            <p className="eyebrow">Access</p>
            <h2>Sign in to Wardn Hub</h2>
          </div>
          <button className="icon-button" onClick={onClose} title="Close" type="button">
            <X size={17} />
          </button>
        </header>
        {notice && <div className="notice">{notice}</div>}
        {error && <div className="error-banner">{error}</div>}
        <div className="auth-modal-grid">
          <form className="form-surface primary-auth" onSubmit={(event) => void submitLogin(event)}>
            <h3>Session login</h3>
            <input
              autoComplete="email"
              onChange={(event) => setEmail(event.target.value)}
              placeholder="admin@example.com"
              type="email"
              value={email}
            />
            <input
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
              placeholder="password"
              type="password"
              value={password}
            />
            <div className="form-actions">
              <button className="text-button" type="submit">
                Login
              </button>
              <button className="small-button" onClick={() => void submitLogout()} type="button">
                Logout
              </button>
            </div>
            {user && <p className="muted">Current session: {user.email}</p>}
          </form>
          <form className="form-surface" onSubmit={(event) => void submitBootstrap(event)}>
            <h3>First-time setup</h3>
            <input
              onChange={(event) => setFirstName(event.target.value)}
              placeholder="First name"
              value={firstName}
            />
            <input
              onChange={(event) => setLastName(event.target.value)}
              placeholder="Last name"
              value={lastName}
            />
            <button className="text-button" type="submit">
              Create superuser
            </button>
          </form>
          <div className="form-surface">
            <h3>Bearer token</h3>
            <input
              onChange={(event) => setToken(event.target.value)}
              placeholder="whub_..."
              value={token}
            />
            <button className="text-button" onClick={saveToken} type="button">
              Save token
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

function BrowseView({ onSubmitServer }: { onSubmitServer: () => void }) {
  const [servers, setServers] = useState<RegistryServerRead[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [detail, setDetail] = useState<RegistryServerVersionRead[]>([]);
  const [state, setState] = useState<LoadState>("idle");
  const [detailState, setDetailState] = useState<LoadState>("idle");
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [supportLevel, setSupportLevel] = useState("");
  const [partnerOnly, setPartnerOnly] = useState(false);

  async function refresh(overrides?: {
    search?: string;
    supportLevel?: string;
    partnerOnly?: boolean;
  }) {
    setState("loading");
    setError("");
    try {
      const response = await listServers({
        search: overrides?.search ?? search,
        supportLevel: overrides?.supportLevel ?? supportLevel,
        partner: (overrides?.partnerOnly ?? partnerOnly) || undefined,
      });
      setServers(response.servers);
      setSelected((current) => current || response.servers[0]?.name || "");
      setState("ready");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load registry.");
      setState(statusFromError(caught));
    }
  }

  useEffect(() => {
    const timeoutId = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timeoutId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected) {
      queueMicrotask(() => setDetail([]));
      return;
    }
    queueMicrotask(() => setDetailState("loading"));
    getServer(selected)
      .then((response) => {
        setDetail(response.versions ?? []);
        setDetailState("ready");
      })
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : "Unable to load server detail.");
        setDetailState(statusFromError(caught));
      });
  }, [selected]);

  const selectedServer = useMemo(
    () => servers.find((server) => server.name === selected),
    [selected, servers],
  );

  function applyChip(chip: (typeof registryChips)[number]) {
    setSearch(chip.search);
    setSupportLevel(chip.supportLevel);
    setPartnerOnly(chip.partnerOnly);
    void refresh({
      search: chip.search,
      supportLevel: chip.supportLevel,
      partnerOnly: chip.partnerOnly,
    });
  }

  function submitSearch(event: React.FormEvent) {
    event.preventDefault();
    void refresh();
  }

  const latestVersions = servers
    .map((server) => ({
      name: server.name,
      title: server.title || server.name,
      version: server.latestVersion?.version,
      updatedAt: server.updatedAt,
    }))
    .filter((server) => server.version)
    .slice(0, 6);

  const verifiedCount = servers.filter((server) => server.namespaceVerified).length;
  const partnerBackedCount = servers.filter(
    (server) => (server.partnerSupport ?? []).length > 0,
  ).length;

  return (
    <div className="home-view">
      <section className="hero-section">
        <div className="hero-grid">
          <div className="hero-copy">
            <p className="eyebrow">MCP Registry</p>
            <h1>Wardn Hub MCP Servers</h1>
            <p className="hero-subtitle">
              Discover MCP servers by trust signal, partner support, and namespace ownership.
            </p>
          </div>
          <div className="registry-status-panel">
            <div>
              <span>Servers</span>
              <strong>{servers.length}</strong>
            </div>
            <div>
              <span>Verified namespaces</span>
              <strong>{verifiedCount}</strong>
            </div>
            <div>
              <span>Partner backed</span>
              <strong>{partnerBackedCount}</strong>
            </div>
          </div>
        </div>
        <form className="hero-search" onSubmit={submitSearch}>
          <label className="search-field large">
            <Search size={18} />
            <input
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search servers, namespaces, owners"
              value={search}
            />
          </label>
          <select
            aria-label="Support level"
            onChange={(event) => setSupportLevel(event.target.value)}
            value={supportLevel}
          >
            {supportLevels.map((level) => (
              <option key={level || "any"} value={level}>
                {level || "Any support"}
              </option>
            ))}
          </select>
          <label className="toggle">
            <input
              checked={partnerOnly}
              onChange={(event) => setPartnerOnly(event.target.checked)}
              type="checkbox"
            />
            <span>Partners</span>
          </label>
          <button className="text-button" type="submit">
            Search
          </button>
        </form>
        <div className="category-strip" aria-label="Registry filters">
          {registryChips.map((chip) => (
            <button
              className={
                search === chip.search &&
                supportLevel === chip.supportLevel &&
                partnerOnly === chip.partnerOnly
                  ? "active"
                  : ""
              }
              key={chip.label}
              onClick={() => applyChip(chip)}
              type="button"
            >
              {chip.label}
            </button>
          ))}
        </div>
      </section>

      <section className="home-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Featured</p>
            <h2>Featured MCPs</h2>
          </div>
          <button className="icon-button" onClick={() => void refresh()} title="Refresh" type="button">
            <RefreshCw size={17} />
          </button>
        </div>
        <div className="catalog-grid">
          <div className="catalog-main">
            {state === "loading" && <EmptyState title="Loading" detail="Fetching registry." />}
            {state === "error" && <EmptyState title="Registry unavailable" detail={error} />}
            {state === "ready" && servers.length === 0 && (
              <div className="empty-catalog">
                <div>
                  <p className="eyebrow">Ready for submissions</p>
                  <h3>No MCP servers published yet</h3>
                  <p>
                    Published submissions will appear as searchable registry cards with namespace,
                    version, support, and review metadata.
                  </p>
                </div>
                <div className="empty-catalog-steps">
                  <span>Review submission</span>
                  <span>Verify namespace</span>
                  <span>Publish version</span>
                </div>
                <button className="text-button" onClick={onSubmitServer} type="button">
                  Submit server
                </button>
              </div>
            )}
            <div className="server-grid">
              {servers.map((server) => (
                <button
                  className={`server-card ${selected === server.name ? "selected" : ""}`}
                  key={server.id}
                  onClick={() => setSelected(server.name)}
                  type="button"
                >
                  <span className="server-card-head">
                    <span>
                      <strong>{server.title || server.name}</strong>
                      <small>{server.name}</small>
                    </span>
                    <Pill tone={toneFor(server.status)}>{server.status}</Pill>
                  </span>
                  <span className="server-card-description">{server.description}</span>
                  <span className="pill-stack">
                    {server.namespaceVerified && (
                      <Pill tone="success">
                        <BadgeCheck size={13} /> namespace
                      </Pill>
                    )}
                    {(server.partnerSupport ?? []).slice(0, 2).map((support) => (
                      <Pill key={`${support.organization.id}-${support.supportLevel}`} tone="success">
                        {support.supportLevel}
                      </Pill>
                    ))}
                    {server.latestVersion?.version && (
                      <Pill tone="neutral">{server.latestVersion.version}</Pill>
                    )}
                  </span>
                </button>
              ))}
            </div>
          </div>
          <aside className="latest-panel">
            <div className="section-heading compact">
              <div>
                <p className="eyebrow">Latest</p>
                <h2>Latest MCPs</h2>
              </div>
            </div>
            {latestVersions.length === 0 && (
              <div className="latest-empty">
                <strong>No published versions</strong>
                <span>Approved releases will appear here as soon as they are published.</span>
              </div>
            )}
            {latestVersions.map((version) => (
              <button
                className="latest-row"
                key={version.name}
                onClick={() => setSelected(version.name)}
                type="button"
              >
                <span>
                  <strong>{version.title}</strong>
                  <small>{version.name}</small>
                </span>
                <span>
                  <Pill tone="neutral">{version.version}</Pill>
                  <small>{formatDate(version.updatedAt)}</small>
                </span>
              </button>
            ))}
          </aside>
        </div>
      </section>

      <section className="topic-section">
        <div className="section-heading compact">
          <div>
            <p className="eyebrow">Popular topics</p>
            <h2>Focused MCP workflows</h2>
          </div>
        </div>
        <div className="topic-grid">
          {topicCards.map((topic) => (
            <button
              className="topic-card"
              key={topic.title}
              onClick={() => {
                setSearch(topic.title);
                void refresh({ search: topic.title });
              }}
              type="button"
            >
              <strong>{topic.title}</strong>
              <span>{topic.detail}</span>
            </button>
          ))}
        </div>
      </section>

      {selectedServer && (
      <section className="registry-layout">
        <aside className="detail-pane">
          <>
              <div className="detail-head">
                <div>
                  <p className="eyebrow">Server Profile</p>
                  <h2>{selectedServer.title || selectedServer.name}</h2>
                  <p>{selectedServer.name}</p>
                </div>
                <Pill tone={toneFor(selectedServer.status)}>{selectedServer.status}</Pill>
              </div>
              <p className="description">{selectedServer.description}</p>
              <div className="metadata-grid">
                <span>Owner</span>
                <strong>{selectedServer.owner?.login ?? "Wardn"}</strong>
                <span>Namespace</span>
                <strong>
                  {selectedServer.namespaceClaim?.namespace ??
                    (selectedServer.namespaceVerified ? "verified" : "unverified")}
                </strong>
                <span>Updated</span>
                <strong>{formatDate(selectedServer.updatedAt)}</strong>
              </div>
              <section className="detail-section">
                <h3>Partner support</h3>
                {(selectedServer.partnerSupport ?? []).length === 0 && (
                  <p className="muted">No active partner support records.</p>
                )}
                {(selectedServer.partnerSupport ?? []).map((support) => (
                  <div className="support-row" key={`${support.organization.id}-${support.supportLevel}`}>
                    <span>{support.organization.name}</span>
                    <Pill tone="success">{support.supportLevel}</Pill>
                  </div>
                ))}
              </section>
              <section className="detail-section">
                <h3>Versions</h3>
                {detailState === "loading" && <p className="muted">Loading versions.</p>}
                {detail.map((version) => (
                  <div className="version-row" key={version.id}>
                    <span>{version.version}</span>
                    <Pill tone={toneFor(version.status)}>{version.status}</Pill>
                    {version.isLatest && <Pill tone="success">latest</Pill>}
                  </div>
                ))}
              </section>
          </>
        </aside>
      </section>
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

function NamespacesView() {
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [claims, setClaims] = useState<NamespaceClaimRead[]>([]);
  const [namespace, setNamespace] = useState("");
  const [method, setMethod] = useState<NamespaceMethod>("github");
  const [notice, setNotice] = useState("");

  async function refresh() {
    setState("loading");
    setError("");
    return listNamespaceClaims()
      .then((response) => {
        setClaims(response.claims);
        setState("ready");
      })
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : "Unable to load namespace claims.");
        setState(statusFromError(caught));
      });
  }

  async function createClaim(event: React.FormEvent) {
    event.preventDefault();
    setNotice("");
    try {
      await createNamespaceClaim({ namespace, method });
      setNamespace("");
      setNotice("Namespace claim created.");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create namespace claim.");
      setState(statusFromError(caught));
    }
  }

  async function mutateClaim(claim: NamespaceClaimRead, action: "verify" | "fail" | "revoke") {
    setNotice("");
    try {
      if (action === "revoke") {
        await revokeNamespaceClaim(claim.id);
      } else {
        await namespaceDecision(claim.id, action, { verificationPayload: {} });
      }
      setNotice(`${action} completed for ${claim.namespace}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Namespace action failed.");
      setState(statusFromError(caught));
    }
  }

  useEffect(() => {
    const timeoutId = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timeoutId);
  }, []);

  return (
    <DataView title="Namespace claims" eyebrow="Trust Plane" icon={ShieldCheck}>
      <ProtectedState state={state} error={error} />
      <form className="inline-form" onSubmit={(event) => void createClaim(event)}>
        <input
          onChange={(event) => setNamespace(event.target.value)}
          placeholder="io.github.example/*"
          required
          value={namespace}
        />
        <select
          onChange={(event) => setMethod(event.target.value as NamespaceMethod)}
          value={method}
        >
          <option value="github">github</option>
          <option value="dns">dns</option>
          <option value="http">http</option>
        </select>
        <button className="text-button" type="submit">
          Claim
        </button>
      </form>
      {notice && <div className="notice">{notice}</div>}
      {state === "ready" && (
        <div className="records">
          {claims.length === 0 && <EmptyState title="No claims" detail="No namespace claims." />}
          {claims.map((claim) => (
            <div className="record-row" key={claim.id}>
              <div>
                <strong>{claim.namespace}</strong>
                <small>{claim.method}</small>
              </div>
              <Pill tone={toneFor(claim.status)}>{claim.status}</Pill>
              <div className="action-strip">
                {claim.status !== "verified" && (
                  <ActionButton onClick={() => void mutateClaim(claim, "verify")}>
                    Verify
                  </ActionButton>
                )}
                {claim.status === "pending" && (
                  <ActionButton onClick={() => void mutateClaim(claim, "fail")}>Fail</ActionButton>
                )}
                {claim.status !== "revoked" && (
                  <ActionButton onClick={() => void mutateClaim(claim, "revoke")}>
                    Revoke
                  </ActionButton>
                )}
                <span>{formatDate(claim.updatedAt)}</span>
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

function SettingsView() {
  return (
    <DataView title="Settings" eyebrow="Runtime" icon={KeyRound}>
      <div className="settings-grid">
        <span>API base URL</span>
        <strong>{process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL}</strong>
        <span>Authentication</span>
        <strong>Session cookie / bearer token</strong>
        <span>Generated client</span>
        <strong>OpenAPI + Orval</strong>
      </div>
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
  const [authOpen, setAuthOpen] = useState(
    () => typeof window !== "undefined" && window.location.search.includes("auth=1"),
  );

  return (
    <AppShell section={section} onOpenAuth={() => setAuthOpen(true)} onSectionChange={setSection}>
      {section === "browse" && <BrowseView onSubmitServer={() => setSection("submissions")} />}
      {section === "submissions" && <SubmissionsView />}
      {section === "partners" && <PartnersView />}
      {section === "namespaces" && <NamespacesView />}
      {section === "audit" && <AuditView />}
      {section === "settings" && <SettingsView />}
      <AuthDialog onClose={() => setAuthOpen(false)} open={authOpen} />
    </AppShell>
  );
}
