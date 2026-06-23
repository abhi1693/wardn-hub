"use client";

import {
  BadgeCheck,
  Building2,
  Database,
  FileCheck2,
  History,
  KeyRound,
  RefreshCw,
  Search,
  Server,
  Settings,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  DEFAULT_API_BASE_URL,
  HubApiError,
  getServer,
  listAuditEvents,
  listNamespaceClaims,
  listPartnerOrganizations,
  listPartnerSupport,
  listServers,
  listSubmissions,
} from "@/lib/api/hub";
import type {
  AuditEventRead,
  NamespaceClaimRead,
  PartnerOrganizationRead,
  PartnerServerSupportRead,
  RegistryServerRead,
  RegistryServerVersionRead,
  SubmissionRead,
} from "@/lib/api/generated/model";

type Section = "browse" | "submissions" | "partners" | "namespaces" | "audit" | "settings";
type LoadState = "idle" | "loading" | "ready" | "error" | "auth";

const navItems: Array<{ id: Section; label: string; icon: typeof Server }> = [
  { id: "browse", label: "Browse", icon: Server },
  { id: "submissions", label: "Submissions", icon: FileCheck2 },
  { id: "partners", label: "Partner Organizations", icon: Building2 },
  { id: "namespaces", label: "Namespaces", icon: ShieldCheck },
  { id: "audit", label: "Audit", icon: History },
  { id: "settings", label: "Settings", icon: Settings },
];

const supportLevels = ["", "official", "verified", "compatible", "deprecated"];

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

function AppShell({
  section,
  onSectionChange,
  children,
}: {
  section: Section;
  onSectionChange: (section: Section) => void;
  children: React.ReactNode;
}) {
  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Database size={18} />
          <span>Wardn Hub</span>
        </div>
        <nav className="nav-list" aria-label="Primary">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={`nav-item ${section === item.id ? "active" : ""}`}
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
      </aside>
      <section className="workspace">{children}</section>
    </main>
  );
}

function BrowseView() {
  const [servers, setServers] = useState<RegistryServerRead[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [detail, setDetail] = useState<RegistryServerVersionRead[]>([]);
  const [state, setState] = useState<LoadState>("idle");
  const [detailState, setDetailState] = useState<LoadState>("idle");
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [supportLevel, setSupportLevel] = useState("");
  const [partnerOnly, setPartnerOnly] = useState(false);

  async function refresh() {
    setState("loading");
    setError("");
    try {
      const response = await listServers({
        search,
        supportLevel,
        partner: partnerOnly || undefined,
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

  return (
    <div className="view">
      <header className="view-header">
        <div>
          <p className="eyebrow">MCP Registry</p>
          <h1>Browse servers</h1>
        </div>
        <button className="icon-button" onClick={refresh} title="Refresh" type="button">
          <RefreshCw size={17} />
        </button>
      </header>
      <div className="toolbar">
        <label className="search-field">
          <Search size={16} />
          <input
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void refresh();
            }}
            placeholder="Search registry"
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
        <button className="text-button" onClick={refresh} type="button">
          Apply
        </button>
      </div>
      <div className="registry-layout">
        <div className="table-surface">
          <div className="server-list-header">
            <span>Name</span>
            <span>Trust</span>
            <span>Latest</span>
          </div>
          <div className="server-list">
            {state === "loading" && <EmptyState title="Loading" detail="Fetching registry." />}
            {state === "error" && <EmptyState title="Request failed" detail={error} />}
            {state === "ready" && servers.length === 0 && (
              <EmptyState title="No servers" detail="No matching registry entries." />
            )}
            {servers.map((server) => (
              <button
                className={`server-row ${selected === server.name ? "selected" : ""}`}
                key={server.id}
                onClick={() => setSelected(server.name)}
                type="button"
              >
                <span>
                  <strong>{server.name}</strong>
                  <small>{server.title || server.description}</small>
                </span>
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
                </span>
                <span>{server.latestVersion?.version ?? ""}</span>
              </button>
            ))}
          </div>
        </div>
        <aside className="detail-pane">
          {!selectedServer && <EmptyState title="No selection" detail="Select a server." />}
          {selectedServer && (
            <>
              <div className="detail-head">
                <div>
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
                <h3>Partner Support</h3>
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
          )}
        </aside>
      </div>
    </div>
  );
}

function SubmissionsView() {
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [submissions, setSubmissions] = useState<SubmissionRead[]>([]);

  useEffect(() => {
    listSubmissions()
      .then((response) => {
        setSubmissions(response.submissions);
        setState("ready");
      })
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : "Unable to load submissions.");
        setState(statusFromError(caught));
      });
  }, []);

  return (
    <DataView title="Submission queue" eyebrow="Moderation" icon={FileCheck2}>
      <ProtectedState state={state} error={error} />
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
              <span>{formatDate(submission.updatedAt)}</span>
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

  useEffect(() => {
    listNamespaceClaims()
      .then((response) => {
        setClaims(response.claims);
        setState("ready");
      })
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : "Unable to load namespace claims.");
        setState(statusFromError(caught));
      });
  }, []);

  return (
    <DataView title="Namespace claims" eyebrow="Trust Plane" icon={ShieldCheck}>
      <ProtectedState state={state} error={error} />
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
              <span>{formatDate(claim.updatedAt)}</span>
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

  useEffect(() => {
    listPartnerOrganizations()
      .then((response) => {
        setPartners(response.organizations);
        setSelected(response.organizations[0]?.id ?? "");
        setState("ready");
      })
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : "Unable to load partners.");
        setState(statusFromError(caught));
      });
  }, []);

  useEffect(() => {
    if (!selected) return;
    queueMicrotask(() => setSupportState("loading"));
    listPartnerSupport(selected)
      .then((response) => {
        setSupport(response.support);
        setSupportState("ready");
      })
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : "Unable to load support records.");
        setSupportState(statusFromError(caught));
      });
  }, [selected]);

  return (
    <DataView title="Partner organizations" eyebrow="Support Metadata" icon={Building2}>
      <ProtectedState state={state} error={error} />
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
            <h2>Server support</h2>
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

  return (
    <AppShell section={section} onSectionChange={setSection}>
      {section === "browse" && <BrowseView />}
      {section === "submissions" && <SubmissionsView />}
      {section === "partners" && <PartnersView />}
      {section === "namespaces" && <NamespacesView />}
      {section === "audit" && <AuditView />}
      {section === "settings" && <SettingsView />}
      <div className="mobile-tabs">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <button
              aria-label={item.label}
              className={section === item.id ? "active" : ""}
              key={item.id}
              onClick={() => setSection(item.id)}
              title={item.label}
              type="button"
            >
              <Icon size={18} />
            </button>
          );
        })}
      </div>
    </AppShell>
  );
}
