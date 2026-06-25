"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Check, Clipboard, ExternalLink } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { ServerIcon, serverIconUrl } from "@/components/server-icon";
import { getServer } from "@/lib/api/hub";
import type {
  RegistryServerDetailResponse,
  RegistryServerVersionRead,
} from "@/lib/api/generated/model";

type LoadState = "loading" | "ready" | "error";
type DetailTab = "overview" | "technical";
type DetailItem = { label: string; value: ReactNode; wide?: boolean };

const technicalManifestHiddenFields = new Set([
  "$schema",
  "_meta",
  "categories",
  "category",
  "description",
  "docs",
  "documentation",
  "homepage",
  "icon",
  "icons",
  "name",
  "packages",
  "readme",
  "readmeUrl",
  "remotes",
  "repo",
  "repository",
  "title",
  "version",
  "website",
  "websiteUrl",
]);

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    : [];
}

function versionTargets(version?: RegistryServerVersionRead) {
  return {
    packages: records(version?.packages),
    remotes: records(version?.remotes),
  };
}

function repositoryUrl(repository: unknown) {
  return repository && typeof repository === "object"
    ? stringValue((repository as Record<string, unknown>).url)
    : "";
}

function isEmptyValue(value: unknown) {
  return (
    value === undefined ||
    value === null ||
    value === "" ||
    (Array.isArray(value) && value.length === 0)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasFields(value: unknown, hiddenFields = new Set<string>()) {
  return (
    isRecord(value) &&
    Object.entries(value).some(([key, item]) => !hiddenFields.has(key) && !isEmptyValue(item))
  );
}

function labelFromKey(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function primitiveText(value: unknown) {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  return "";
}

function isUrlValue(value: string) {
  return /^https?:\/\//.test(value);
}

function actorLabel(actor: unknown) {
  if (!actor || typeof actor !== "object") return "Not available";
  const record = actor as Record<string, unknown>;
  return stringValue(record.name) || stringValue(record.login) || stringValue(record.id) || "Not available";
}

function ActorValue({ actor }: { actor: unknown }) {
  if (!actor || typeof actor !== "object") return <>Not available</>;
  const record = actor as Record<string, unknown>;
  const label = actorLabel(actor);
  const actorType = stringValue(record.type);
  const actorId = stringValue(record.id);
  const href = stringValue(record.htmlUrl) || stringValue(record.url);

  if (actorType === "User" && actorId) {
    return (
      <Link className="server-detail-inline-link" href={`/users/${encodeURIComponent(actorId)}`}>
        {label}
      </Link>
    );
  }
  if (!href) return <>{label}</>;
  return (
    <a href={href} rel="noreferrer" target="_blank">
      {label}
      <ExternalLink size={14} />
    </a>
  );
}

function formatDate(value?: string | null) {
  if (!value) return "Not available";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function targetValue(item: Record<string, unknown>, fallback: string) {
  return (
    stringValue(item.identifier) ||
    stringValue(item.url) ||
    stringValue(item.name) ||
    stringValue(item.package) ||
    fallback
  );
}

function targetType(item: Record<string, unknown>, fallback: string) {
  return (
    stringValue(item.registryType) ||
    stringValue(item.transport) ||
    stringValue(item.type) ||
    fallback
  );
}

function nestedRecord(value: Record<string, unknown>, key: string) {
  return isRecord(value[key]) ? value[key] : {};
}

function valueOrFallback(value: string, fallback = "Not specified") {
  return value || fallback;
}

function formatTone(value: string) {
  const normalized = value.toLowerCase();
  if (["boolean", "bool"].includes(normalized)) return "boolean";
  if (["integer", "number", "float", "double"].includes(normalized)) return "number";
  if (["uri", "url", "email", "hostname"].includes(normalized)) return "network";
  if (["json", "object", "array"].includes(normalized)) return "structured";
  if (["secret", "password", "token"].includes(normalized)) return "secret";
  return "string";
}

function FormatBadge({ value }: { value: string }) {
  return <span className={`technical-badge tone-${formatTone(value)}`}>{value}</span>;
}

function BooleanMark({ value }: { value: unknown }) {
  const enabled = value === true;

  return (
    <span
      aria-label={enabled ? "Yes" : "No"}
      className={`technical-boolean ${enabled ? "yes" : "no"}`}
      title={enabled ? "Yes" : "No"}
    >
      {enabled ? <Check size={16} /> : "x"}
    </span>
  );
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);

  async function copyValue() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <button
      aria-label="Copy target"
      className="server-detail-copy"
      onClick={() => void copyValue()}
      title="Copy target"
      type="button"
    >
      {copied ? <Check size={16} /> : <Clipboard size={16} />}
    </button>
  );
}

function TechnicalHeader({
  count,
  title,
}: {
  count?: string;
  title: string;
}) {
  return (
    <div className="technical-card-header">
      <h2>{title}</h2>
      {count ? <span>{count}</span> : null}
    </div>
  );
}

function DetailGrid({ items }: { items: DetailItem[] }) {
  return (
    <dl className="server-detail-field-grid">
      {items.map((item) => (
        <div className={item.wide ? "wide" : ""} key={item.label}>
          <dt>{item.label}</dt>
          <dd>{isEmptyValue(item.value) ? "Not available" : item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ExternalTextLink({ href, children }: { href: string; children: ReactNode }) {
  if (!href) return <>Not available</>;
  return (
    <a href={href} rel="noreferrer" target="_blank">
      {children}
      <ExternalLink size={14} />
    </a>
  );
}

function VisualValue({ hiddenFields, value }: { hiddenFields?: Set<string>; value: unknown }) {
  if (isEmptyValue(value)) return <span className="server-detail-muted">Not available</span>;

  if (Array.isArray(value)) {
    const primitives = value.filter((item) => !isRecord(item) && !Array.isArray(item));
    const objects = value.filter((item): item is Record<string, unknown> => isRecord(item));

    return (
      <div className="server-detail-value-stack">
        {primitives.length > 0 ? (
          <div className="server-detail-chip-list">
            {primitives.map((item, index) => (
              <span key={`${primitiveText(item)}-${index}`}>{primitiveText(item)}</span>
            ))}
          </div>
        ) : null}
        {objects.map((item, index) => (
          <div className="server-detail-nested-fields" key={index}>
            <VisualFields hiddenFields={hiddenFields} value={item} />
          </div>
        ))}
      </div>
    );
  }

  if (isRecord(value)) return <VisualFields hiddenFields={hiddenFields} value={value} />;

  const text = primitiveText(value);
  if (isUrlValue(text)) {
    return (
      <a href={text} rel="noreferrer" target="_blank">
        {text}
        <ExternalLink size={14} />
      </a>
    );
  }

  return <>{text}</>;
}

function VisualFields({
  hiddenFields = new Set<string>(),
  value,
}: {
  hiddenFields?: Set<string>;
  value: Record<string, unknown>;
}) {
  const entries = Object.entries(value).filter(
    ([key, item]) => !hiddenFields.has(key) && !isEmptyValue(item),
  );

  if (entries.length === 0) {
    return null;
  }

  return (
    <dl className="server-detail-visual-fields">
      {entries.map(([key, item]) => (
        <div key={key}>
          <dt>{labelFromKey(key)}</dt>
          <dd>
            <VisualValue hiddenFields={hiddenFields} value={item} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function DocumentationBlock({ value }: { value: string }) {
  return (
    <div className="server-detail-doc">
      <ReactMarkdown
        components={{
          a: ({ children, href }) => (
            <a href={href} rel="noreferrer" target={href?.startsWith("http") ? "_blank" : undefined}>
              {children}
            </a>
          ),
        }}
        remarkPlugins={[remarkGfm]}
      >
        {value}
      </ReactMarkdown>
    </div>
  );
}

function PackageEnvironmentTable({
  environmentVariables,
}: {
  environmentVariables: Record<string, unknown>[];
}) {
  const rows = environmentVariables.map((envVar) => ({
    defaultValue: stringValue(envVar.default),
    description: stringValue(envVar.description),
    format: stringValue(envVar.format) || "string",
    name: stringValue(envVar.name),
    required: envVar.isRequired,
    secret: envVar.isSecret,
  })).filter((envVar) => envVar.name);

  if (rows.length === 0) return null;

  return (
    <div className="technical-nested-table">
      <label>Environment Variables</label>
      <div className="technical-table-wrap">
        <table className="technical-table compact">
          <thead>
            <tr>
              <th>Name</th>
              <th>Format</th>
              <th>Secret</th>
              <th>Required</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((envVar) => (
              <tr key={envVar.name}>
                <td>
                  <strong>{envVar.name}</strong>
                  {envVar.description ? <span>{envVar.description}</span> : null}
                  {envVar.defaultValue ? <em>Default: {envVar.defaultValue}</em> : null}
                </td>
                <td>
                  <FormatBadge value={envVar.format} />
                </td>
                <td>
                  <BooleanMark value={envVar.secret} />
                </td>
                <td>
                  <BooleanMark value={envVar.required} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PackageArgumentsTable({
  packages,
}: {
  packages: Record<string, unknown>[];
}) {
  const rows = packages.flatMap((packageTarget) =>
    records(packageTarget.packageArguments).map((argument) => ({
      defaultValue: stringValue(argument.default),
      description: stringValue(argument.description),
      flag: stringValue(argument.flag),
      format: stringValue(argument.format) || "string",
      identifier: targetValue(packageTarget, "Package"),
      name: stringValue(argument.name),
      options: Array.isArray(argument.options) ? argument.options.map(String).join(", ") : "",
      required: argument.isRequired,
      secret: argument.isSecret,
      value: stringValue(argument.value),
    })),
  ).filter((argument) => argument.name || argument.flag);

  if (rows.length === 0) return null;

  return (
    <section className="technical-card">
      <TechnicalHeader count={`${rows.length} defined`} title="Package Arguments" />
      <div className="technical-table-wrap">
        <table className="technical-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Package</th>
              <th>Flag</th>
              <th>Format</th>
              <th>Required</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((argument, index) => (
              <tr key={`${argument.identifier}-${argument.name}-${argument.flag}-${index}`}>
                <td>
                  <strong>{argument.name || argument.flag}</strong>
                  {argument.description ? <span>{argument.description}</span> : null}
                  {argument.defaultValue ? <em>Default: {argument.defaultValue}</em> : null}
                  {argument.options ? <em>Options: {argument.options}</em> : null}
                </td>
                <td>{argument.identifier}</td>
                <td>{argument.flag || "Not specified"}</td>
                <td>
                  <FormatBadge value={argument.format} />
                </td>
                <td>
                  <BooleanMark value={argument.required} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RemotesPanel({ remotes }: { remotes: Record<string, unknown>[] }) {
  if (remotes.length === 0) return null;

  return (
    <section className="technical-card">
      <TechnicalHeader count={`${remotes.length} defined`} title="Remotes" />
      <div className="technical-remote-list">
        {remotes.map((remote, index) => {
          const url = stringValue(remote.url);
          const headers = records(remote.headers);
          const environmentVariables = records(remote.environmentVariables);
          const remoteType = targetType(remote, "remote");
          return (
            <details className="technical-package-item" key={`${url}-${index}`} open={index === 0}>
              <summary>
                <span>
                  <strong>{valueOrFallback(url, "Remote endpoint")}</strong>
                  <em>{remoteType}</em>
                </span>
              </summary>
              <div className="technical-package-body">
                <div className="technical-remote-grid">
                  <div>
                    <label>Endpoint URL</label>
                    <div className="technical-code-field">
                      <span>{valueOrFallback(url)}</span>
                      {url ? <CopyButton value={url} /> : null}
                    </div>
                  </div>
                  <div>
                    <label>Transport Type</label>
                    <strong>{remoteType}</strong>
                  </div>
                </div>

                {headers.length > 0 ? (
                  <div className="technical-subtable">
                    <label>Headers</label>
                    <table className="technical-table compact">
                      <thead>
                        <tr>
                          <th>Name</th>
                          <th>Required</th>
                          <th>Secret</th>
                          <th>Description</th>
                        </tr>
                      </thead>
                      <tbody>
                        {headers.map((header, headerIndex) => (
                          <tr key={`${stringValue(header.name)}-${headerIndex}`}>
                            <td>
                              <strong>{valueOrFallback(stringValue(header.name))}</strong>
                            </td>
                            <td>
                              <BooleanMark value={header.isRequired} />
                            </td>
                            <td>
                              <BooleanMark value={header.isSecret} />
                            </td>
                            <td>{stringValue(header.description) || "Not specified"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}

                <PackageEnvironmentTable environmentVariables={environmentVariables} />
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}

function PackageDefinitionPanel({ packages }: { packages: Record<string, unknown>[] }) {
  if (packages.length === 0) return null;

  return (
    <section className="technical-card">
      <TechnicalHeader count={`${packages.length} defined`} title="Package Definitions" />
      <div className="technical-package-list">
        {packages.map((packageTarget, index) => {
          const identifier = targetValue(packageTarget, "Package");
          const transport = nestedRecord(packageTarget, "transport");
          const transportType = stringValue(transport.type) || "stdio";
          const environmentVariables = records(packageTarget.environmentVariables);
          return (
            <details className="technical-package-item" key={`${identifier}-${index}`} open={index === 0}>
              <summary>
                <span>
                  <strong>{identifier}</strong>
                  <em>
                    {targetType(packageTarget, "package")} · {transportType}
                  </em>
                </span>
              </summary>
              <div className="technical-package-body">
                <div>
                  <label>Identifier</label>
                  <div className="technical-code-field">
                    <span>{identifier}</span>
                    <CopyButton value={identifier} />
                  </div>
                </div>
                <div className="technical-pair-grid">
                  <div>
                    <label>Type</label>
                    <strong>{targetType(packageTarget, "package")}</strong>
                  </div>
                  <div>
                    <label>Transport</label>
                    <strong>{transportType}</strong>
                  </div>
                  {stringValue(packageTarget.version) ? (
                    <div>
                      <label>Version</label>
                      <strong>{stringValue(packageTarget.version)}</strong>
                    </div>
                  ) : null}
                </div>
                <VisualFields
                  hiddenFields={
                    new Set(["identifier", "registryType", "transport", "version", "environmentVariables", "packageArguments"])
                  }
                  value={packageTarget}
                />
                <PackageEnvironmentTable environmentVariables={environmentVariables} />
              </div>
            </details>
        );
      })}
      </div>
    </section>
  );
}

function ManifestMetadataPanel({
  manifest,
  version,
}: {
  manifest: Record<string, unknown> | null;
  version?: string;
}) {
  if (!manifest) return null;

  const schema = stringValue(manifest.$schema);
  const meta = isRecord(manifest._meta) ? manifest._meta : null;

  if (!schema && !version && !meta) return null;

  return (
    <section className="technical-side-card">
      <h2>Manifest</h2>
      <div className="technical-side-stack">
        {version ? (
          <div>
            <label>Version</label>
            <strong>{version}</strong>
          </div>
        ) : null}
        {schema ? (
          <div>
            <label>Schema</label>
            <a className="technical-link break" href={schema} rel="noreferrer" target="_blank">
              {schema}
              <ExternalLink size={14} />
            </a>
          </div>
        ) : null}
        {meta ? (
          <div>
            <label>Publisher Metadata</label>
            <VisualFields value={meta} />
          </div>
        ) : null}
      </div>
    </section>
  );
}

function ManifestFieldsPanel({ manifest }: { manifest: Record<string, unknown> | null }) {
  if (!hasFields(manifest, technicalManifestHiddenFields) || !manifest) return null;

  return (
    <section className="technical-card">
      <TechnicalHeader title="Manifest Fields" />
      <VisualFields hiddenFields={technicalManifestHiddenFields} value={manifest} />
    </section>
  );
}

export default function ServerDetailPage() {
  const params = useParams<{ serverName?: string[] }>();
  const serverName = (params.serverName ?? []).join("/");
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<RegistryServerDetailResponse | null>(null);
  const [activeTab, setActiveTab] = useState<DetailTab>("overview");
  const [selectedVersionId, setSelectedVersionId] = useState("");

  useEffect(() => {
    if (!serverName) return;
    const timeoutId = window.setTimeout(() => {
      setState("loading");
      setError("");
      getServer(serverName)
        .then((response) => {
          setDetail(response);
          setState("ready");
        })
        .catch((caught) => {
          setError(caught instanceof Error ? caught.message : "Unable to load server.");
          setState("error");
        });
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [serverName]);

  const server = detail?.server;
  const versions = useMemo(() => detail?.versions ?? [], [detail?.versions]);
  const latestVersion = useMemo(
    () => versions.find((version) => version.isLatest) ?? versions[0],
    [versions],
  );
  const selectedVersion = useMemo(
    () => versions.find((version) => version.id === selectedVersionId) ?? latestVersion,
    [latestVersion, selectedVersionId, versions],
  );

  const targets = useMemo(() => versionTargets(selectedVersion), [selectedVersion]);
  const repoUrl = repositoryUrl(selectedVersion?.repository ?? server?.repository);
  const title = selectedVersion?.title || server?.title || server?.name || "MCP Server";
  const description = selectedVersion?.description || server?.description || "";
  const documentation = selectedVersion?.documentation || server?.documentation || "";
  const websiteUrl = selectedVersion?.websiteUrl || server?.websiteUrl || "";
  const category = selectedVersion?.categories?.[0] ?? server?.categories?.[0];
  const categoryName = category?.name || "MCP Server";
  const partnerSupport = selectedVersion?.partnerSupport?.length
    ? selectedVersion.partnerSupport
    : server?.partnerSupport ?? [];
  const manifest = isRecord(selectedVersion?.serverJson) ? selectedVersion.serverJson : null;
  const hasDocumentation = Boolean(documentation.trim());
  const hasPartnerSupport = partnerSupport.length > 0;
  const hasVersions = versions.length > 0;
  const versionPickerOptions = hasVersions
    ? versions.map((version) => ({
        id: version.id,
        isLatest: version.isLatest,
        version: version.version,
      }))
    : server?.latestVersion
      ? [
          {
            id: server.latestVersion.id,
            isLatest: true,
            version: server.latestVersion.version,
          },
        ]
      : [];

  return (
    <div className="server-detail-page">
      <header className="server-detail-topbar">
        <Link className="server-detail-brand" href="/">
          Wardn Hub
        </Link>
        <nav>
          <Link href="/">Explore</Link>
          <Link href="/categories">Categories</Link>
          <Link href="/users">Users</Link>
          <Link href="/submissions">Submissions</Link>
          <Link className="server-detail-nav-cta" href="/submit">
            List Server
          </Link>
        </nav>
      </header>

      <main className="server-detail-main">
        {state === "loading" ? (
          <div className="empty-state">
            <div className="empty-title">Loading</div>
            <div className="empty-detail">Fetching server details.</div>
          </div>
        ) : null}

        {state === "error" ? (
          <div className="empty-state">
            <div className="empty-title">Server unavailable</div>
            <div className="empty-detail">{error}</div>
          </div>
        ) : null}

        {state === "ready" && server ? (
          <>
            <section className="server-detail-hero">
              <div className="server-detail-logo">
                <ServerIcon src={serverIconUrl(server)} title={title} />
              </div>
              <div className="server-detail-title">
                <h1>{title}</h1>
                <p>{server.name}</p>
              </div>
              {versionPickerOptions.length > 0 ? (
                <label className="server-version-picker" aria-label="Select version">
                  <select
                    onChange={(event) => setSelectedVersionId(event.target.value)}
                    value={selectedVersion?.id ?? versionPickerOptions[0]?.id ?? ""}
                  >
                    {versionPickerOptions.map((version) => (
                      <option key={version.id} value={version.id}>
                        {version.version}
                        {version.isLatest ? " (latest)" : ""}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
            </section>

            <div className="server-detail-tabs" role="tablist" aria-label="Server detail views">
              <button
                aria-selected={activeTab === "overview"}
                className={activeTab === "overview" ? "active" : ""}
                onClick={() => setActiveTab("overview")}
                role="tab"
                type="button"
              >
                Overview
              </button>
              <button
                aria-selected={activeTab === "technical"}
                className={activeTab === "technical" ? "active" : ""}
                onClick={() => setActiveTab("technical")}
                role="tab"
                type="button"
              >
                Technical
              </button>
            </div>

            <div className="server-detail-layout">
              {activeTab === "overview" ? (
                <>
                  <div className="server-detail-content">
                    <section className="server-detail-card">
                      <h2>Overview</h2>
                      <p className="server-detail-summary">{description}</p>
                      <div className="server-detail-links">
                        {websiteUrl ? (
                          <a href={websiteUrl} rel="noreferrer" target="_blank">
                            Website
                            <ExternalLink size={16} />
                          </a>
                        ) : null}
                        {repoUrl ? (
                          <a href={repoUrl} rel="noreferrer" target="_blank">
                            Repository
                            <ExternalLink size={16} />
                          </a>
                        ) : null}
                      </div>
                    </section>

                    {hasPartnerSupport ? (
                      <section className="server-detail-card">
                        <h2>Partner Support</h2>
                        <div className="server-detail-support-list">
                          {partnerSupport.map((support, index) => (
                            <div key={`${support.organization.id}-${index}`}>
                              <strong>{actorLabel(support.organization)}</strong>
                              <DetailGrid
                                items={[
                                  { label: "Level", value: support.supportLevel },
                                  { label: "Status", value: support.supportStatus },
                                  { label: "Starts", value: formatDate(support.startsAt) },
                                  { label: "Ends", value: formatDate(support.endsAt) },
                                  {
                                    label: "Docs",
                                    value: (
                                      <ExternalTextLink href={support.docsUrl}>
                                        Documentation
                                      </ExternalTextLink>
                                    ),
                                  },
                                  {
                                    label: "Support",
                                    value: (
                                      <ExternalTextLink href={support.supportUrl}>Support</ExternalTextLink>
                                    ),
                                  },
                                ]}
                              />
                            </div>
                          ))}
                        </div>
                      </section>
                    ) : null}

                    {hasDocumentation ? (
                      <section className="server-detail-card">
                        <h2>Documentation</h2>
                        <DocumentationBlock value={documentation} />
                      </section>
                    ) : null}
                  </div>

                  <aside className="server-detail-sidebar">
                    <section className="server-detail-card">
                      <h2>{versions.length > 1 ? "Selected Version" : "Latest Version"}</h2>
                      <dl className="server-detail-list">
                        <div>
                          <dt>Version</dt>
                          <dd>{selectedVersion?.version ?? "Not published"}</dd>
                        </div>
                        <div>
                          <dt>Category</dt>
                          <dd>
                            {category?.slug ? (
                              <Link
                                className="server-detail-inline-link"
                                href={`/categories/${encodeURIComponent(category.slug)}`}
                              >
                                {categoryName}
                              </Link>
                            ) : (
                              categoryName
                            )}
                          </dd>
                        </div>
                        <div>
                          <dt>Published</dt>
                          <dd>{formatDate(selectedVersion?.publishedAt)}</dd>
                        </div>
                        <div>
                          <dt>Updated</dt>
                          <dd>{formatDate(selectedVersion?.updatedAt ?? server.updatedAt)}</dd>
                        </div>
                        <div>
                          <dt>Published By</dt>
                          <dd>
                            <ActorValue actor={selectedVersion?.publishedBy} />
                          </dd>
                        </div>
                      </dl>
                    </section>

                  </aside>
                </>
              ) : (
                <>
                  <div className="technical-main">
                    <PackageDefinitionPanel packages={targets.packages} />
                    <PackageArgumentsTable packages={targets.packages} />
                    <RemotesPanel remotes={targets.remotes} />
                    <ManifestFieldsPanel manifest={manifest} />
                  </div>

                  <aside className="technical-sidebar">
                    <ManifestMetadataPanel manifest={manifest} version={selectedVersion?.version} />
                  </aside>
                </>
              )}
            </div>
          </>
        ) : null}
      </main>
    </div>
  );
}
