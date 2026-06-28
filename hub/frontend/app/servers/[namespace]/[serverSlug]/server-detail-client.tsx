"use client";

import Link from "next/link";
import { Check, Clipboard, ExternalLink } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import { ServerIcon, serverIconUrl } from "@/components/server-icon";
import { PublicHeader } from "@/components/site-header";
import { claimServerOwnership, currentUser, getServer } from "@/lib/api/hub";
import type {
  RegistryServerDetailResponse,
  RegistryServerVersionRead,
  RegistryTrustReport,
  RegistryTrustReportComponent,
  UserRead,
} from "@/lib/api/generated/model";
import { publicRegistryUrl } from "@/lib/site";

type LoadState = "loading" | "ready" | "error";
type DetailTab = "overview" | "schema" | "score";
type DetailItem = { label: string; value: ReactNode; wide?: boolean };
type RepositoryReference = {
  branch?: string;
  source?: string;
  subfolder?: string;
  tag?: string;
  url?: string;
};

const packageHiddenFields = new Set([
  "environmentVariables",
  "identifier",
  "packageArguments",
  "registryType",
  "transport",
  "version",
]);

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    : [];
}

function strings(value: unknown) {
  return Array.isArray(value)
    ? value.map((item) => String(item)).filter(Boolean)
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

function repositoryReference(repository: unknown): RepositoryReference | null {
  if (!repository || typeof repository !== "object") return null;
  const record = repository as Record<string, unknown>;
  const reference = {
    branch: stringValue(record.branch),
    source: stringValue(record.source),
    subfolder: stringValue(record.subfolder),
    tag: stringValue(record.tag),
    url: stringValue(record.url),
  };
  return reference.url ? reference : null;
}

function githubRepositoryParts(repository: RepositoryReference | null) {
  const url = repository?.url?.replace(/\.git$/, "") ?? "";
  const match = url.match(/^(?:https?:\/\/github\.com\/)?([^/\s]+)\/([^/\s#?]+)$/);
  if (!match) return null;
  return { owner: match[1], repo: match[2] };
}

function encodePath(value: string) {
  return value
    .split("/")
    .filter(Boolean)
    .map((part) => encodeURIComponent(part))
    .join("/");
}

function qualityBadgePath(serverName: string, version?: string) {
  const path = `/api/v1/mcp/badges/quality/${encodePath(serverName)}`;
  if (!version) return path;
  return `${path}?${new URLSearchParams({ version }).toString()}`;
}

function qualityBadgeUrl(serverName: string, version?: string) {
  return publicRegistryUrl(qualityBadgePath(serverName, version));
}

function wardnOwnershipSnippet(serverName: string, userId: string) {
  return JSON.stringify(
    {
      $schema: "https://wardn.ai/schemas/wardn.json",
      servers: {
        [serverName]: {
          owners: [{ userId }],
        },
      },
    },
    null,
    2,
  );
}

function trustScoreLabel(score?: number | null) {
  return typeof score === "number" ? `${score}/100` : "Pending";
}

function trustSourceLabel(source?: string) {
  if (source === "manual") return "Scorer evidence";
  if (source === "calculated") return "Hub fallback";
  return "Pending";
}

function trustSourceDetail(source?: string) {
  if (source === "manual") return "Based on scorer-collected registry, source, package, and metadata evidence.";
  if (source === "calculated") return "Based on available Hub registry metadata while scorer evidence is incomplete.";
  return "This report is waiting for enough evidence to produce a trust assessment.";
}

function trustScorePercent(score?: number | null) {
  if (typeof score !== "number") return 0;
  return Math.max(0, Math.min(100, score));
}

function trustScoreBand(score?: number | null) {
  if (typeof score !== "number") return "Pending";
  if (score >= 90) return "Strong";
  if (score >= 70) return "Good";
  if (score >= 40) return "Limited";
  return "Weak";
}

function trustStatusTone(status?: string, score?: number | null) {
  if (status === "passed" || (typeof score === "number" && score >= 90)) return "passed";
  if (status === "failed" || (typeof score === "number" && score < 40)) return "failed";
  if (status === "warning" || (typeof score === "number" && score < 70)) return "warning";
  return "unknown";
}

function trustEvidenceCount(components: RegistryTrustReportComponent[]) {
  return components.reduce((total, component) => total + (component.evidence?.length ?? 0), 0);
}

function isWardnOwnershipClaimed(report: RegistryTrustReport | null) {
  const ownerVerification = report?.components?.find(
    (component) => component.key === "ownerVerification",
  );
  if (!ownerVerification) return false;
  const text = [ownerVerification.summary, ...(ownerVerification.evidence ?? [])]
    .join(" ")
    .toLowerCase();
  return text.includes("wardn.json");
}

function shouldOpenTrustComponent(component: RegistryTrustReportComponent) {
  return (
    component.status !== "passed" ||
    typeof component.score !== "number" ||
    component.score < 90 ||
    (component.evidence?.length ?? 0) === 0
  );
}

const trustComponentGuidance: Record<string, { missing: string; improve: string }> = {
  schemaCompleteness: {
    missing: "Manifest fields, package/remotes, or structured capability metadata may be incomplete.",
    improve: "Publish complete server metadata, transport details, package targets, capabilities, and version fields.",
  },
  documentation: {
    missing: "Setup, configuration, examples, or operational notes may not be complete enough for evaluation.",
    improve: "Add installation steps, configuration requirements, examples, expected transports, and troubleshooting notes.",
  },
  sourceReview: {
    missing: "Wardn may have limited source files, repository structure, or review evidence.",
    improve: "Expose a reachable source repository and include reviewable README, package, lockfile, and workflow files.",
  },
  targetMetadata: {
    missing: "Package or remote endpoint metadata may be incomplete or not independently inspectable.",
    improve: "Publish package registry identifiers, versions, transport metadata, and remote URLs where applicable.",
  },
  license: {
    missing: "A machine-readable license was not found in enough registry, package, or repository metadata.",
    improve: "Publish an SPDX license in the repository, package metadata, or submitted manifest.",
  },
  maintenance: {
    missing: "Recent commit, release, or update signals may be stale or unavailable.",
    improve: "Keep source/package metadata current and expose recent commit, release, or published update evidence.",
  },
  ownerVerification: {
    missing: "Organization ownership, official partner support, or source/domain ownership proof has not been added.",
    improve: "Claim the server under an organization or add official-source verification through partner/support metadata.",
  },
  securityReview: {
    missing: "Security review, secret handling, dependency review, or vulnerability evidence may be incomplete.",
    improve: "Publish security review status, SECURITY.md, lockfiles, CI checks, and secret-safe environment metadata.",
  },
};

function trustGuidanceFor(component: RegistryTrustReportComponent) {
  return (
    trustComponentGuidance[component.key] ?? {
      missing: "Wardn does not have enough structured evidence to fully explain this component.",
      improve: "Add structured registry metadata and source evidence for this area.",
    }
  );
}

function githubRef(repository: RepositoryReference | null) {
  if (repository?.tag) return `refs/tags/${repository.tag}`;
  return `refs/heads/${repository?.branch || "main"}`;
}

function githubDisplayRef(repository: RepositoryReference | null) {
  return repository?.tag || repository?.branch || "main";
}

function repositoryRelativePath(value: string, repository: RepositoryReference | null) {
  const subfolder = repository?.subfolder?.replace(/^\/+|\/+$/g, "") ?? "";
  const basePath = subfolder ? `/${subfolder}/` : "/";
  return new URL(value, `https://github.invalid${basePath}`).pathname.replace(/^\/+/, "");
}

function isExternalOrAnchorUrl(value: string) {
  return /^(?:[a-z][a-z0-9+.-]*:|\/\/|#)/i.test(value);
}

function resolveRepositoryImageUrl(value: string | undefined, repository: RepositoryReference | null) {
  if (!value) return value;
  const trimmed = value.trim();
  if (!trimmed || isExternalOrAnchorUrl(trimmed)) return value;
  const parts = githubRepositoryParts(repository);
  if (!parts) return value;
  const path = repositoryRelativePath(trimmed, repository);
  return `https://raw.githubusercontent.com/${parts.owner}/${parts.repo}/${encodePath(githubRef(repository))}/${encodePath(path)}`;
}

function resolveRepositoryLinkUrl(value: string | undefined, repository: RepositoryReference | null) {
  if (!value) return value;
  const trimmed = value.trim();
  if (!trimmed || isExternalOrAnchorUrl(trimmed)) return value;
  const parts = githubRepositoryParts(repository);
  if (!parts) return value;
  const path = repositoryRelativePath(trimmed, repository);
  return `https://github.com/${parts.owner}/${parts.repo}/blob/${encodePath(githubDisplayRef(repository))}/${encodePath(path)}`;
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

function normalizedFieldKey(value: string) {
  return value.replace(/[^a-z0-9]/gi, "").toLowerCase();
}

function isHiddenField(key: string, hiddenFields: Set<string>) {
  if (hiddenFields.has(key)) return true;
  const normalizedKey = normalizedFieldKey(key);
  return Array.from(hiddenFields).some((field) => normalizedFieldKey(field) === normalizedKey);
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

type TechnicalPillTone =
  | "boolean"
  | "command"
  | "neutral"
  | "network"
  | "number"
  | "package"
  | "secret"
  | "string"
  | "structured"
  | "transport"
  | "warning";

function formatTone(value: string): TechnicalPillTone {
  const normalized = value.toLowerCase();
  if (["boolean", "bool"].includes(normalized)) return "boolean";
  if (["integer", "number", "float", "double"].includes(normalized)) return "number";
  if (["uri", "url", "email", "hostname"].includes(normalized)) return "network";
  if (["json", "object", "array"].includes(normalized)) return "structured";
  if (["secret", "password", "token"].includes(normalized)) return "secret";
  return "string";
}

function packageTone(value: string): TechnicalPillTone {
  const normalized = value.toLowerCase();
  if (["npm", "pypi", "uvx", "oci", "docker", "container"].includes(normalized)) {
    return "package";
  }
  return "neutral";
}

function transportTone(value: string): TechnicalPillTone {
  const normalized = value.toLowerCase();
  if (["http", "https", "sse", "streamable-http", "websocket", "ws"].includes(normalized)) {
    return "network";
  }
  if (["stdio", "local"].includes(normalized)) return "transport";
  return "neutral";
}

function TechnicalPill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: TechnicalPillTone;
}) {
  return <span className={`technical-pill tone-${tone}`}>{children}</span>;
}

function FormatBadge({ value }: { value: string }) {
  return <TechnicalPill tone={formatTone(value)}>{value}</TechnicalPill>;
}

function RegistryTypePill({ value }: { value: string }) {
  return <TechnicalPill tone={packageTone(value)}>{value}</TechnicalPill>;
}

function TransportTypePill({ value }: { value: string }) {
  return <TechnicalPill tone={transportTone(value)}>{value}</TechnicalPill>;
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

function RequirementMark({ value }: { value: unknown }) {
  if (typeof value !== "boolean") {
    return (
      <span aria-label="Unknown" className="technical-boolean unknown" title="Unknown">
        ?
      </span>
    );
  }

  return <BooleanMark value={value} />;
}

async function writeClipboardText(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.top = "-9999px";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();

  try {
    if (!document.execCommand("copy")) {
      throw new Error("Copy command was rejected");
    }
  } finally {
    textarea.remove();
  }
}

function CopyButton({ label = "Copy target", value }: { label?: string; value: string }) {
  const [copied, setCopied] = useState(false);

  async function copyValue() {
    try {
      await writeClipboardText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch (error) {
      console.error("Unable to copy value to the clipboard.", error);
    }
  }

  return (
    <button
      aria-label={label}
      className="server-detail-copy"
      onClick={() => void copyValue()}
      title={label}
      type="button"
    >
      {copied ? <Check size={16} /> : <Clipboard size={16} />}
    </button>
  );
}

function QualityBadgePanel({
  badgePreviewUrl,
  badgeUrl,
  markdown,
  score,
}: {
  badgePreviewUrl: string;
  badgeUrl: string;
  markdown: string;
  score?: number | null;
}) {
  return (
    <section className="server-detail-card server-detail-badge-card">
      <div className="server-detail-card-title-row">
        <h2>README Badge</h2>
        <CopyButton label="Copy Markdown" value={markdown} />
      </div>
      <a className="server-detail-badge-preview" href={badgeUrl} rel="noreferrer" target="_blank">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          alt={`Wardn Score: ${typeof score === "number" ? `${score}/100` : "pending"}`}
          height={20}
          src={badgePreviewUrl}
        />
      </a>
      <div className="server-detail-markdown-snippet">
        <code>{markdown}</code>
      </div>
    </section>
  );
}

function OwnershipClaimPanel({
  claimed,
  error,
  notice,
  onClaim,
  claiming,
  serverName,
  userId,
}: {
  claimed: boolean;
  error: string;
  notice: string;
  onClaim: () => void;
  claiming: boolean;
  serverName: string;
  userId: string;
}) {
  const snippet = wardnOwnershipSnippet(serverName, userId);

  return (
    <section className="server-detail-card server-detail-claim-card">
      <div className="server-detail-card-title-row">
        <h2>{claimed ? "Ownership Claimed" : "Claim Ownership"}</h2>
        {!claimed ? (
          <button
            className="server-detail-claim-button"
            disabled={claiming}
            onClick={onClaim}
            type="button"
          >
            {claiming ? "Verifying" : "Claim"}
          </button>
        ) : null}
      </div>
      {claimed ? (
        <p className="server-detail-muted">
          Ownership is verified from wardn.json.
        </p>
      ) : (
        <>
          <p className="server-detail-muted">
            Add this file at the root of the linked GitHub repository or website, then verify
            ownership.
          </p>
          <div className="server-detail-card-title-row compact">
            <span className="server-detail-muted">wardn.json template</span>
            <CopyButton label="Copy wardn.json" value={snippet} />
          </div>
          <div className="server-detail-markdown-snippet ownership-snippet">
            <code>{snippet}</code>
          </div>
        </>
      )}
      {notice ? <div className="notice compact">{notice}</div> : null}
      {error ? <div className="error-banner compact">{error}</div> : null}
    </section>
  );
}

function TrustReportPanel({ report }: { report: RegistryTrustReport }) {
  const components = report.components ?? [];
  const evidenceCount = trustEvidenceCount(components);
  const reportTone = trustStatusTone(report.status, report.overallScore);

  return (
    <section className="server-detail-card server-detail-trust-card">
      <div className="server-detail-card-title-row">
        <h2>Trust Report</h2>
        <TechnicalPill tone={reportTone === "failed" ? "warning" : "structured"}>
          {trustSourceLabel(report.scoreSource)}
        </TechnicalPill>
      </div>
      <div className="trust-report-score">
        <div className="trust-report-score-heading">
          <strong>{trustScoreLabel(report.overallScore)}</strong>
          <span className={`trust-report-grade status-${reportTone}`}>{trustScoreBand(report.overallScore)}</span>
        </div>
        <span>{report.summary || "Trust report is pending."}</span>
        <span className="trust-report-track">
          <span
            className={`trust-report-fill status-${reportTone}`}
            style={{ width: `${trustScorePercent(report.overallScore)}%` }}
          />
        </span>
      </div>
      <div className="trust-report-meta-grid">
        <div>
          <span>Source</span>
          <strong>{trustSourceLabel(report.scoreSource)}</strong>
          <p>{trustSourceDetail(report.scoreSource)}</p>
        </div>
        <div>
          <span>Evidence</span>
          <strong>
            {evidenceCount} item{evidenceCount === 1 ? "" : "s"}
          </strong>
          <p>
            Across {components.length} component{components.length === 1 ? "" : "s"} in this version report.
          </p>
        </div>
      </div>
      <div className="trust-report-legend" aria-label="Score ranges">
        <span>
          <strong>90-100</strong> Strong
        </span>
        <span>
          <strong>70-89</strong> Good
        </span>
        <span>
          <strong>40-69</strong> Limited
        </span>
        <span>
          <strong>0-39</strong> Weak
        </span>
      </div>
      {components.length > 0 ? (
        <div className="trust-report-components">
          {components.map((component) => (
            <TrustReportComponentRow component={component} key={component.key} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

function TrustReportComponentRow({ component }: { component: RegistryTrustReportComponent }) {
  const [open, setOpen] = useState(() => shouldOpenTrustComponent(component));
  const guidance = trustGuidanceFor(component);
  const componentTone = trustStatusTone(component.status, component.score);
  const evidence = component.evidence ?? [];

  return (
    <details
      className={`trust-report-component status-${componentTone}`}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary>
        <span>
          <strong>{component.label}</strong>
          <em>{component.summary}</em>
        </span>
        <span className={`trust-report-component-grade status-${componentTone}`}>
          {trustScoreBand(component.score)}
        </span>
      </summary>
      <div className="trust-report-component-body">
        <div>
          <h3>What Wardn Found</h3>
          {evidence.length ? (
            <ul>
              {evidence.map((item, index) => (
                <li key={`${component.key}-${index}`}>{item}</li>
              ))}
            </ul>
          ) : (
            <p>No evidence item was published for this component.</p>
          )}
        </div>
        <div>
          <h3>Missing Signals</h3>
          <p>{guidance.missing}</p>
        </div>
        <div>
          <h3>Improve By</h3>
          <p>{guidance.improve}</p>
        </div>
      </div>
    </details>
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
    ([key, item]) => !isHiddenField(key, hiddenFields) && !isEmptyValue(item),
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

const documentationSanitizeSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    a: [...(defaultSchema.attributes?.a ?? []), "href", "title"],
    div: [...(defaultSchema.attributes?.div ?? []), "align"],
    img: [
      ...(defaultSchema.attributes?.img ?? []),
      "alt",
      "height",
      "loading",
      "src",
      "title",
      "width",
    ],
  },
};

function DocumentationBlock({
  repository,
  value,
}: {
  repository: RepositoryReference | null;
  value: string;
}) {
  return (
    <div className="server-detail-doc">
      <ReactMarkdown
        components={{
          a: ({ children, href }) => {
            const resolvedHref = resolveRepositoryLinkUrl(href, repository);
            return (
              <a
                href={resolvedHref}
                rel="noreferrer"
                target={resolvedHref?.startsWith("http") ? "_blank" : undefined}
              >
                {children}
              </a>
            );
          },
          img: ({ alt, height, src, title, width }) => {
            const imageSrc = typeof src === "string" ? src : undefined;
            return (
              <img
                alt={alt ?? ""}
                height={height}
                loading="lazy"
                src={resolveRepositoryImageUrl(imageSrc, repository)}
                title={title}
                width={width}
              />
            );
          },
        }}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, documentationSanitizeSchema]]}
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
                  <RequirementMark value={envVar.required} />
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
  packageArguments,
}: {
  packageArguments: Record<string, unknown>[];
}) {
  const rows = packageArguments
    .map((argument) => ({
      defaultValue: stringValue(argument.default),
      description: stringValue(argument.description),
      flag: stringValue(argument.flag),
      format: stringValue(argument.format) || "string",
      includeInLaunch: argument.includeInLaunch,
      name: stringValue(argument.name),
      options: Array.isArray(argument.options) ? argument.options.map(String).join(", ") : "",
      required: argument.isRequired,
      secret: argument.isSecret,
      value: stringValue(argument.value),
      requiresValue: argument.requiresValue ?? argument.requires_value,
    }))
    .filter((argument) => argument.name || argument.flag || argument.value);

  if (rows.length === 0) return null;

  return (
    <div className="technical-subtable">
      <label>Package Arguments</label>
      <div className="technical-table-wrap">
        <table className="technical-table compact">
          <thead>
            <tr>
              <th>Name</th>
              <th>Takes Value</th>
              <th>Format</th>
              <th>Required</th>
              <th>Launch</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((argument, index) => (
              <tr key={`${argument.name}-${argument.flag}-${index}`}>
                <td>
                  <strong>{argument.name || argument.flag}</strong>
                  {argument.description ? <span>{argument.description}</span> : null}
                  {argument.defaultValue ? <em>Default: {argument.defaultValue}</em> : null}
                  {argument.options ? <em>Options: {argument.options}</em> : null}
                </td>
                <td>
                  <BooleanMark value={argument.requiresValue} />
                  {argument.value ? <span>{argument.value}</span> : null}
                </td>
                <td>
                  <FormatBadge value={argument.format} />
                </td>
                <td>
                  <BooleanMark value={argument.required} />
                </td>
                <td>
                  <BooleanMark value={argument.includeInLaunch} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
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
          const queryParameters = records(remote.queryParameters ?? remote.queryParams);
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
                              <BooleanMark value={header.isRequired ?? header.required} />
                            </td>
                            <td>
                              <BooleanMark value={header.isSecret ?? header.secret} />
                            </td>
                            <td>{stringValue(header.description) || "Not specified"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}

                {queryParameters.length > 0 ? (
                  <div className="technical-subtable">
                    <label>Query Parameters</label>
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
                        {queryParameters.map((parameter, parameterIndex) => (
                          <tr key={`${stringValue(parameter.name)}-${parameterIndex}`}>
                            <td>
                              <strong>{valueOrFallback(stringValue(parameter.name))}</strong>
                            </td>
                            <td>
                              <BooleanMark value={parameter.isRequired ?? parameter.required} />
                            </td>
                            <td>
                              <BooleanMark value={parameter.isSecret ?? parameter.secret} />
                            </td>
                            <td>{stringValue(parameter.description) || "Not specified"}</td>
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
          const command = stringValue(transport.command);
          const transportArguments = strings(transport.args);
          const transportType = stringValue(transport.type) || "stdio";
          const environmentVariables = records(packageTarget.environmentVariables);
          const packageArguments = records(packageTarget.packageArguments);
          const fullCommand = [command, ...transportArguments].filter(Boolean).join(" ");
          return (
            <details className="technical-package-item" key={`${identifier}-${index}`} open={index === 0}>
              <summary>
                <span>
                  <strong>{identifier}</strong>
                  <em>
                    <RegistryTypePill value={targetType(packageTarget, "package")} />
                    <TransportTypePill value={transportType} />
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
                    <RegistryTypePill value={targetType(packageTarget, "package")} />
                  </div>
                  <div>
                    <label>Transport</label>
                    <TransportTypePill value={transportType} />
                  </div>
                  {stringValue(packageTarget.version) ? (
                    <div>
                      <label>Version</label>
                      <TechnicalPill tone="number">{stringValue(packageTarget.version)}</TechnicalPill>
                    </div>
                  ) : null}
                </div>
                {fullCommand ? (
                  <div className="technical-pair-grid">
                    <div className="wide">
                      <label>Command</label>
                      <div className="technical-code-field">
                        <span>{fullCommand}</span>
                        <CopyButton value={fullCommand} />
                      </div>
                    </div>
                  </div>
                ) : null}
                <VisualFields hiddenFields={packageHiddenFields} value={packageTarget} />
                <PackageEnvironmentTable environmentVariables={environmentVariables} />
                <PackageArgumentsTable packageArguments={packageArguments} />
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

  if (!schema && !version) return null;

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
      </div>
    </section>
  );
}

const detailTabs: { id: DetailTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "schema", label: "Schema" },
  { id: "score", label: "Score" },
];

function EmptyDetailPanel({ detail, title }: { detail: string; title: string }) {
  return (
    <section className="server-detail-card">
      <h2>{title}</h2>
      <p className="server-detail-muted">{detail}</p>
    </section>
  );
}

export function ServerDetailClient({
  initialDetail,
  initialError = "",
  serverName,
}: {
  initialDetail: RegistryServerDetailResponse | null;
  initialError?: string;
  serverName: string;
}) {
  const [state, setState] = useState<LoadState>(initialDetail ? "ready" : "error");
  const [error, setError] = useState(initialError);
  const [detail, setDetail] = useState<RegistryServerDetailResponse | null>(initialDetail);
  const [activeTab, setActiveTab] = useState<DetailTab>("overview");
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [currentAccount, setCurrentAccount] = useState<UserRead | null>(null);
  const [claimingOwnership, setClaimingOwnership] = useState(false);
  const [claimError, setClaimError] = useState("");
  const [claimNotice, setClaimNotice] = useState("");

  useEffect(() => {
    if (initialDetail || !serverName) return;
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
  }, [initialDetail, serverName]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      currentUser()
        .then((user) => setCurrentAccount(user))
        .catch(() => setCurrentAccount(null));
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, []);

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
  const repository = repositoryReference(selectedVersion?.repository ?? server?.repository);
  const repoUrl = repositoryUrl(selectedVersion?.repository ?? server?.repository);
  const title = selectedVersion?.title || server?.title || server?.name || "MCP Server";
  const description = selectedVersion?.description || server?.description || "";
  const documentation = selectedVersion?.documentation || server?.documentation || "";
  const websiteUrl = selectedVersion?.websiteUrl || server?.websiteUrl || "";
  const category = server?.categories?.[0];
  const categoryName = category?.name ?? "";
  const badgeVersion = selectedVersion && !selectedVersion.isLatest ? selectedVersion.version : "";
  const badgePreviewUrl = server?.name ? qualityBadgePath(server.name, badgeVersion) : "";
  const badgeUrl = server?.name ? qualityBadgeUrl(server.name, badgeVersion) : "";
  const badgeMarkdown = server?.name
    ? `[![Wardn Score](${badgeUrl})](${publicRegistryUrl(`/servers/${encodePath(server.name)}`)})`
    : "";
  const qualityScore = selectedVersion?.qualityScore ?? server?.qualityScore ?? null;
  const trustReport = selectedVersion?.trustReport ?? server?.trustReport ?? null;
  const partnerSupport = selectedVersion?.partnerSupport?.length
    ? selectedVersion.partnerSupport
    : server?.partnerSupport ?? [];
  const manifest = isRecord(selectedVersion?.serverJson) ? selectedVersion.serverJson : null;
  const isOwnershipClaimed = isWardnOwnershipClaimed(trustReport);
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

  async function claimOwnership() {
    if (!server?.name || !currentAccount?.id) return;
    setClaimingOwnership(true);
    setClaimError("");
    setClaimNotice("");
    try {
      const response = await claimServerOwnership(server.name);
      setDetail({ server: response.server, versions: response.versions });
      setClaimNotice("Ownership verified from wardn.json.");
    } catch (caught) {
      setClaimError(caught instanceof Error ? caught.message : "Unable to verify wardn.json.");
    } finally {
      setClaimingOwnership(false);
    }
  }

  return (
    <div className="server-detail-page">
      <PublicHeader />

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
              {detailTabs.map((tab) => (
                <button
                  aria-selected={activeTab === tab.id}
                  className={activeTab === tab.id ? "active" : ""}
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  role="tab"
                  type="button"
                >
                  {tab.label}
                </button>
              ))}
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
                        <DocumentationBlock repository={repository} value={documentation} />
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
                        {categoryName ? (
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
                        ) : null}
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
              ) : null}

              {activeTab === "schema" ? (
                <>
                  <div className="technical-main">
                    <PackageDefinitionPanel packages={targets.packages} />
                    <RemotesPanel remotes={targets.remotes} />
                  </div>

                  <aside className="technical-sidebar">
                    <ManifestMetadataPanel manifest={manifest} version={selectedVersion?.version} />
                  </aside>
                </>
              ) : null}

              {activeTab === "score" ? (
                <>
                  <div className="server-detail-content">
                    {trustReport ? (
                      <TrustReportPanel report={trustReport} />
                    ) : (
                      <EmptyDetailPanel
                        detail="No trust report has been published for this version."
                        title="Trust Report"
                      />
                    )}
                  </div>
                  <aside className="server-detail-sidebar">
                    {server?.name && currentAccount?.id ? (
                      <OwnershipClaimPanel
                        claimed={isOwnershipClaimed}
                        claiming={claimingOwnership}
                        error={claimError}
                        notice={claimNotice}
                        onClaim={() => void claimOwnership()}
                        serverName={server.name}
                        userId={currentAccount.id}
                      />
                    ) : null}
                    {badgeUrl && badgeMarkdown ? (
                      <QualityBadgePanel
                        badgePreviewUrl={badgePreviewUrl}
                        badgeUrl={badgeUrl}
                        markdown={badgeMarkdown}
                        score={qualityScore}
                      />
                    ) : null}
                  </aside>
                </>
              ) : null}
            </div>
          </>
        ) : null}
      </main>
    </div>
  );
}
