import Link from "next/link";

import type {
  RegistryServerDetailResponse,
  RegistryServerRead,
} from "@/lib/api/generated/model";
import {
  getPublishedRegistryServer,
  listPublishedRegistryServers,
  serverDetailPath,
} from "@/lib/public-registry";

export type ProgrammaticPageKind = "integration" | "registry" | "transport";

export type ProgrammaticPageConfig = {
  criteria: { label: string; value: string }[];
  description: string;
  filterValue?: string;
  h1: string;
  intro: string[];
  kind: ProgrammaticPageKind;
  match: (server: RegistryServerRead, detail?: RegistryServerDetailResponse) => boolean;
  path: string;
  query?: string;
  shortName: string;
  slug: string;
  title: string;
};

type ProgrammaticPageData = {
  details: RegistryServerDetailResponse[];
  error: string;
  servers: RegistryServerRead[];
};

const SERVER_LIMIT = 120;
const DETAIL_LIMIT = 30;

function stringValue(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item),
      )
    : [];
}

function normalize(value: string) {
  return value.trim().toLowerCase();
}

function scoreValue(server: RegistryServerRead) {
  return server.qualityScore ?? server.latestVersion?.qualityScore ?? null;
}

function scoreLabel(score: number | null | undefined) {
  return typeof score === "number" ? `${score}/100` : "Pending";
}

function dateLabel(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat("en", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

function sortedServers(servers: RegistryServerRead[]) {
  return [...servers].sort((left, right) => {
    const leftScore = scoreValue(left) ?? -1;
    const rightScore = scoreValue(right) ?? -1;
    if (rightScore !== leftScore) return rightScore - leftScore;
    return right.updatedAt.localeCompare(left.updatedAt);
  });
}

function latestVersion(detail: RegistryServerDetailResponse) {
  return detail.versions?.find((version) => version.isLatest) ?? detail.versions?.[0] ?? null;
}

function packages(detail: RegistryServerDetailResponse) {
  return records(latestVersion(detail)?.packages);
}

function remotes(detail: RegistryServerDetailResponse) {
  return records(latestVersion(detail)?.remotes);
}

function packageRegistry(packageTarget: Record<string, unknown>) {
  return normalize(
    stringValue(packageTarget.registryType) ||
      stringValue(packageTarget.registry_type) ||
      stringValue(packageTarget.type),
  );
}

function packageTransport(packageTarget: Record<string, unknown>) {
  return normalize(stringValue(recordValue(packageTarget.transport).type) || "stdio");
}

function remoteTransport(remoteTarget: Record<string, unknown>) {
  return normalize(stringValue(remoteTarget.type) || stringValue(remoteTarget.transport));
}

function packageCommand(packageTarget: Record<string, unknown>) {
  const transport = recordValue(packageTarget.transport);
  const command = stringValue(transport.command);
  const args = Array.isArray(transport.args) ? transport.args.map(String).filter(Boolean) : [];
  return [command, ...args].filter(Boolean).join(" ");
}

function packageTarget(packageTarget: Record<string, unknown>) {
  return (
    stringValue(packageTarget.identifier) ||
    stringValue(packageTarget.package) ||
    stringValue(packageTarget.name) ||
    "Package target"
  );
}

function repositoryUrl(server: RegistryServerRead, detail?: RegistryServerDetailResponse) {
  const version = detail ? latestVersion(detail) : null;
  return (
    stringValue(recordValue(version?.repository).url) ||
    stringValue(recordValue(server.repository).url)
  );
}

function textMatchesGithub(server: RegistryServerRead, detail?: RegistryServerDetailResponse) {
  const searchable = [
    server.name,
    server.title,
    server.description,
    server.websiteUrl,
    repositoryUrl(server, detail),
    ...(detail ? packages(detail).flatMap((item) => [packageTarget(item), packageCommand(item)]) : []),
    ...(detail ? remotes(detail).map((item) => stringValue(item.url)) : []),
  ]
    .join(" ")
    .toLowerCase();
  return searchable.includes("github");
}

function detailForServer(details: RegistryServerDetailResponse[], server: RegistryServerRead) {
  return details.find((detail) => detail.server.id === server.id || detail.server.name === server.name);
}

async function fetchDetails(servers: RegistryServerRead[]) {
  const results = await Promise.allSettled(
    sortedServers(servers)
      .slice(0, DETAIL_LIMIT)
      .map((server) => getPublishedRegistryServer(server.name)),
  );
  return results
    .filter((result): result is PromiseFulfilledResult<RegistryServerDetailResponse> => result.status === "fulfilled")
    .map((result) => result.value);
}

function matchingPackageRows(config: ProgrammaticPageConfig, data: ProgrammaticPageData) {
  const rows = data.details.flatMap((detail) => {
    const server = data.servers.find((item) => item.id === detail.server.id) ?? detail.server;
    return packages(detail)
      .filter((packageItem) => {
        if (config.kind === "registry") return packageRegistry(packageItem) === config.filterValue;
        if (config.kind === "transport") return packageTransport(packageItem) === config.filterValue;
        return textMatchesGithub(server, detail);
      })
      .map((packageItem) => ({
        command: packageCommand(packageItem),
        packageTarget: packageTarget(packageItem),
        registry: packageRegistry(packageItem) || "package",
        server,
        transport: packageTransport(packageItem) || "stdio",
        version: stringValue(packageItem.version) || latestVersion(detail)?.version || "Unknown",
      }));
  });

  if (config.kind !== "transport" || config.filterValue !== "streamable-http") return rows;

  const remoteRows = data.details.flatMap((detail) => {
    const server = data.servers.find((item) => item.id === detail.server.id) ?? detail.server;
    return remotes(detail)
      .filter((remote) => remoteTransport(remote) === "streamable-http")
      .map((remote) => ({
        command: stringValue(remote.url),
        packageTarget: stringValue(remote.name) || stringValue(remote.url) || "Remote endpoint",
        registry: "remote",
        server,
        transport: remoteTransport(remote),
        version: latestVersion(detail)?.version || "Unknown",
      }));
  });

  return [...rows, ...remoteRows];
}

function commonConfiguration(data: ProgrammaticPageData) {
  const envVars = new Set<string>();
  const args = new Set<string>();

  data.details.forEach((detail) => {
    packages(detail).forEach((packageItem) => {
      records(packageItem.environmentVariables).forEach((envVar) => {
        const name = stringValue(envVar.name);
        if (name) envVars.add(name);
      });
      records(packageItem.packageArguments).forEach((argument) => {
        const name =
          stringValue(argument.flag) || stringValue(argument.name) || stringValue(argument.value);
        if (name) args.add(name);
      });
    });
    remotes(detail).forEach((remote) => {
      records(remote.environmentVariables).forEach((envVar) => {
        const name = stringValue(envVar.name);
        if (name) envVars.add(name);
      });
    });
  });

  return {
    args: [...args].slice(0, 8),
    envVars: [...envVars].slice(0, 8),
  };
}

function listText(values: string[], fallback: string) {
  if (values.length === 0) return fallback;
  if (values.length === 1) return values[0];
  return `${values.slice(0, -1).join(", ")} and ${values.at(-1)}`;
}

function hasPackageRegistry(registryType: string) {
  return (_server: RegistryServerRead, detail?: RegistryServerDetailResponse) =>
    Boolean(detail && packages(detail).some((item) => packageRegistry(item) === registryType));
}

function hasTransport(transportType: string) {
  return (_server: RegistryServerRead, detail?: RegistryServerDetailResponse) =>
    Boolean(
      detail &&
        (packages(detail).some((item) => packageTransport(item) === transportType) ||
          remotes(detail).some((item) => remoteTransport(item) === transportType)),
    );
}

export const PROGRAMMATIC_PAGES: ProgrammaticPageConfig[] = [
  {
    criteria: [
      { label: "Transport", value: "stdio" },
      { label: "Best fit", value: "Local tools, CLIs, desktop hosts, and package-launched MCP servers" },
      { label: "Configuration focus", value: "Launch command, package target, environment variables, and CLI flags" },
    ],
    description:
      "Compare stdio MCP servers with package commands, configuration metadata, quality scores, and installation targets.",
    filterValue: "stdio",
    h1: "Best stdio MCP Servers",
    intro: [
      "Stdio MCP servers run as local child processes and communicate with an MCP host over standard input and output. This pattern is common for developer tools because it keeps the server close to local files, command-line utilities, package managers, and authenticated developer environments.",
      "Use this page when you want an MCP server that can be launched by a client such as Claude Desktop, an IDE, or another local host. The important comparison points are the package registry, exact launch command, runtime arguments, environment variables, and whether the upstream project documents safe setup instructions.",
      "Wardn Hub ranks and lists these servers from published registry metadata. The table below favors entries with stronger quality scores and recent updates, then exposes the package and transport details that matter when turning registry metadata into a working client configuration.",
    ],
    kind: "transport",
    match: hasTransport("stdio"),
    path: "/transports/stdio",
    shortName: "stdio",
    slug: "stdio",
    title: "Best stdio MCP Servers - Local Package Transports and Configuration",
  },
  {
    criteria: [
      { label: "Transport", value: "streamable-http" },
      { label: "Best fit", value: "Hosted MCP endpoints, shared services, and network-accessible tools" },
      { label: "Configuration focus", value: "Endpoint URL, authentication, headers, and client transport support" },
    ],
    description:
      "Compare streamable HTTP MCP servers with endpoint metadata, package targets, configuration requirements, and trust signals.",
    filterValue: "streamable-http",
    h1: "Best streamable HTTP MCP Servers",
    intro: [
      "Streamable HTTP MCP servers expose Model Context Protocol capabilities over a network endpoint instead of relying only on a local subprocess. They are useful when a tool should be hosted once and consumed by multiple clients, deployed behind existing web infrastructure, or connected through service authentication.",
      "When evaluating streamable HTTP entries, focus on the endpoint shape, authentication model, required headers, environment variables, and whether the server also provides a package for local development. Client compatibility matters because not every MCP host supports the same remote transport features.",
      "Wardn Hub uses published package and remote metadata to surface servers that declare streamable HTTP support. The server list and package table are intended as a starting point for evaluation; always verify the upstream documentation before routing sensitive data to a hosted endpoint.",
    ],
    kind: "transport",
    match: hasTransport("streamable-http"),
    path: "/transports/streamable-http",
    shortName: "streamable HTTP",
    slug: "streamable-http",
    title: "Best Streamable HTTP MCP Servers - Remote MCP Endpoint Directory",
  },
  {
    criteria: [
      { label: "Registry", value: "npm" },
      { label: "Best fit", value: "JavaScript and TypeScript MCP servers distributed through npm" },
      { label: "Configuration focus", value: "Package identifier, version, npx/npm command, args, and environment variables" },
    ],
    description:
      "Compare npm MCP servers by package target, launch command, quality score, version metadata, and setup requirements.",
    filterValue: "npm",
    h1: "Best npm MCP Servers",
    intro: [
      "NPM is one of the most common distribution channels for MCP servers because many developer-tool integrations are written in JavaScript or TypeScript and can be launched directly with package-manager commands. For users, npm-based servers are often easy to test because the package identifier maps directly to an install or run command.",
      "A strong npm MCP listing should show the package name, published version, transport type, launch command, required environment variables, and any server-specific arguments. Those fields are more useful than a generic description because they tell an MCP client operator how the package becomes a running server.",
      "This Wardn Hub page groups published MCP servers that declare npm package metadata. Use the tables to compare install targets, quality scores, update freshness, and configuration requirements before deciding which package belongs in a local or team MCP setup.",
    ],
    kind: "registry",
    match: hasPackageRegistry("npm"),
    path: "/registries/npm",
    shortName: "npm",
    slug: "npm",
    title: "Best npm MCP Servers - Packages, Commands, and Configuration",
  },
  {
    criteria: [
      { label: "Registry", value: "pypi" },
      { label: "Best fit", value: "Python MCP servers launched with uvx, pipx, or Python package tooling" },
      { label: "Configuration focus", value: "Package identifier, version, command, Python runtime hints, and secrets" },
    ],
    description:
      "Compare PyPI MCP servers by Python package metadata, launch commands, environment variables, versions, and trust signals.",
    filterValue: "pypi",
    h1: "Best PyPI MCP Servers",
    intro: [
      "PyPI MCP servers are a natural fit for Python-heavy workflows, data tools, automation scripts, and infrastructure integrations that already live in Python environments. They are commonly launched with uvx, pipx, or another package runner that installs the Python package and starts the MCP server process.",
      "The key evaluation questions are practical: which package should be installed, which command starts the server, what transport does it expose, which environment variables are required, and whether the version metadata is current enough for your client environment.",
      "Wardn Hub groups PyPI-based MCP servers from published package metadata so developers can compare Python package targets without reading every upstream repository first. The server list should still be treated as registry metadata, not a substitute for upstream installation and security review.",
    ],
    kind: "registry",
    match: hasPackageRegistry("pypi"),
    path: "/registries/pypi",
    shortName: "PyPI",
    slug: "pypi",
    title: "Best PyPI MCP Servers - Python Packages and MCP Configuration",
  },
  {
    criteria: [
      { label: "Integration", value: "GitHub" },
      { label: "Best fit", value: "Repository, issue, pull request, workflow, and source-control automation" },
      { label: "Configuration focus", value: "Repository URL, token scopes, environment variables, and command transport" },
    ],
    description:
      "Compare GitHub MCP servers and source-control integrations by repository metadata, configuration requirements, and quality signals.",
    h1: "Best GitHub MCP Servers",
    intro: [
      "GitHub MCP servers connect AI clients to source-control workflows such as reading repositories, inspecting issues, summarizing pull requests, automating triage, and coordinating developer tasks. These integrations are high leverage because they let an assistant work with the project context developers already use.",
      "GitHub integrations also carry security risk. Most useful setups require tokens, repository permissions, organization access, or workflow visibility. Before installing a server, compare the documented scopes, environment variables, transport command, repository ownership, and whether the server is actively maintained.",
      "This page groups Wardn Hub entries that reference GitHub in server metadata, repository URLs, package targets, or descriptions. Use it to shortlist source-control MCP servers, then verify upstream docs and token handling before connecting a real organization or private repository.",
    ],
    kind: "integration",
    match: textMatchesGithub,
    path: "/integrations/github",
    query: "github",
    shortName: "GitHub",
    slug: "github",
    title: "Best GitHub MCP Servers - Repository, PR, and Issue Integrations",
  },
];

export function programmaticPagesForKind(kind: ProgrammaticPageKind) {
  return PROGRAMMATIC_PAGES.filter((page) => page.kind === kind);
}

export function programmaticPageForSlug(kind: ProgrammaticPageKind, slug: string) {
  return PROGRAMMATIC_PAGES.find((page) => page.kind === kind && page.slug === slug);
}

export async function getProgrammaticPageData(config: ProgrammaticPageConfig) {
  try {
    const initialServers = await listPublishedRegistryServers({
      limit: SERVER_LIMIT,
      registryType: config.kind === "registry" ? config.filterValue : undefined,
      search: config.query,
      transportType: config.kind === "transport" ? config.filterValue : undefined,
    });
    const details = await fetchDetails(initialServers);
    const matchedServers = sortedServers(
      initialServers.filter((server) => config.match(server, detailForServer(details, server))),
    );

    return {
      details,
      error: "",
      servers: matchedServers,
    };
  } catch (caught) {
    return {
      details: [],
      error: caught instanceof Error ? caught.message : "Unable to load matching MCP servers.",
      servers: [],
    };
  }
}

function ProgrammaticOverviewTable({ config }: { config: ProgrammaticPageConfig }) {
  return (
    <section className="category-landing-section" aria-labelledby="programmatic-criteria">
      <div className="category-section-header">
        <h2 id="programmatic-criteria">Evaluation criteria</h2>
        <p>
          These are the practical checks to run before adding a matching MCP server to a client or
          team workflow.
        </p>
      </div>
      <div className="category-table-wrap">
        <table className="category-top-table">
          <thead>
            <tr>
              <th>Criterion</th>
              <th>What to verify</th>
            </tr>
          </thead>
          <tbody>
            {config.criteria.map((criterion) => (
              <tr key={criterion.label}>
                <td>{criterion.label}</td>
                <td>{criterion.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ProgrammaticServerTable({
  config,
  data,
}: {
  config: ProgrammaticPageConfig;
  data: ProgrammaticPageData;
}) {
  const rows = matchingPackageRows(config, data).slice(0, 12);
  const servers = data.servers.slice(0, 12);

  return (
    <section className="category-landing-section" aria-labelledby="programmatic-server-table">
      <div className="category-section-header">
        <h2 id="programmatic-server-table">Matching server list</h2>
        <p>
          This table is generated from published Wardn Hub registry records and sampled version
          details for the current page topic.
        </p>
      </div>
      <div className="category-table-wrap">
        <table className="category-top-table">
          <thead>
            <tr>
              <th>Server</th>
              <th>{config.kind === "integration" ? "Repository or target" : "Package or endpoint"}</th>
              <th>Transport</th>
              <th>Score</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {(rows.length > 0 ? rows : servers.map((server) => ({
              command: repositoryUrl(server) || server.websiteUrl,
              packageTarget: server.description,
              registry: "registry",
              server,
              transport: config.shortName,
              version: server.latestVersion?.version ?? "Unknown",
            }))).map((row) => (
              <tr key={`${row.server.id}:${row.packageTarget}:${row.transport}`}>
                <td>
                  <Link href={serverDetailPath(row.server.name)}>
                    {row.server.title || row.server.name}
                  </Link>
                  <span>{row.server.name}</span>
                </td>
                <td>
                  <strong>{row.packageTarget}</strong>
                  <span>{row.command || row.version}</span>
                </td>
                <td>{row.transport}</td>
                <td>{scoreLabel(scoreValue(row.server))}</td>
                <td>{dateLabel(row.server.updatedAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ProgrammaticConfigBlock({ data }: { data: ProgrammaticPageData }) {
  const configuration = commonConfiguration(data);

  return (
    <section className="category-landing-section" aria-labelledby="programmatic-config">
      <div className="category-section-header">
        <h2 id="programmatic-config">Common configuration requirements</h2>
        <p>
          Registry metadata is most useful when it exposes launch requirements before installation.
        </p>
      </div>
      <div className="category-config-grid">
        <article className="category-config-card">
          <h3>Environment variables</h3>
          <p>
            Common variables in sampled matching records include{" "}
            {listText(configuration.envVars, "no shared environment variable names")}. Verify
            secrets and token scopes upstream before use.
          </p>
        </article>
        <article className="category-config-card">
          <h3>Runtime arguments</h3>
          <p>
            Published package arguments include{" "}
            {listText(configuration.args, "no shared command arguments")}. Check defaults and
            required values before pasting commands into an MCP client.
          </p>
        </article>
        <article className="category-config-card">
          <h3>Trust checks</h3>
          <p>
            Compare Wardn Score, update date, package target, repository ownership, and upstream
            documentation. Treat registry data as a shortlist, not final approval.
          </p>
        </article>
      </div>
    </section>
  );
}

function ProgrammaticFaq({
  config,
  data,
}: {
  config: ProgrammaticPageConfig;
  data: ProgrammaticPageData;
}) {
  const faqs = [
    {
      answer: `The best ${config.shortName} MCP servers are the matching published entries with clear package or endpoint metadata, recent updates, strong Wardn scores, and documented configuration requirements.`,
      question: `What are the best ${config.shortName} MCP servers?`,
    },
    {
      answer: `Start with the ${data.servers.length} matching Wardn Hub records on this page, compare score and update freshness, then inspect the individual server page for package commands, environment variables, and upstream documentation.`,
      question: `How should I compare these MCP servers?`,
    },
    {
      answer:
        "No. Wardn Hub is a registry and discovery product. Always verify upstream documentation, required secrets, permissions, and client compatibility before installing or connecting a server.",
      question: "Can I install directly from this page?",
    },
  ];

  return (
    <section className="category-landing-section" aria-labelledby="programmatic-faq">
      <div className="category-section-header">
        <h2 id="programmatic-faq">FAQ</h2>
      </div>
      <div className="category-faq-grid">
        {faqs.map((faq) => (
          <article className="category-faq-item" key={faq.question}>
            <h3>{faq.question}</h3>
            <p>{faq.answer}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

export function ProgrammaticLandingPage({
  config,
  data,
}: {
  config: ProgrammaticPageConfig;
  data: ProgrammaticPageData;
}) {
  return (
    <main className="server-detail-main">
      <section className="category-page-header">
        <div>
          <p className="category-page-kicker">
            {config.kind === "transport" ? "MCP transport" : null}
            {config.kind === "registry" ? "Package registry" : null}
            {config.kind === "integration" ? "MCP integration" : null}
          </p>
          <h1>{config.h1}</h1>
          <p>{config.description}</p>
        </div>
      </section>

      {data.error ? (
        <div className="empty-state">
          <div className="empty-title">Server list unavailable</div>
          <div className="empty-detail">{data.error}</div>
        </div>
      ) : null}

      <section className="category-landing-summary" aria-label={`${config.shortName} summary`}>
        <div>
          <strong>{data.servers.length}</strong>
          <span>matching servers</span>
        </div>
        <div>
          <strong>{matchingPackageRows(config, data).length}</strong>
          <span>sampled targets</span>
        </div>
        <div>
          <strong>{data.details.length}</strong>
          <span>detail records reviewed</span>
        </div>
      </section>

      <section className="category-landing-section" aria-labelledby="programmatic-overview">
        <div className="category-section-header">
          <h2 id="programmatic-overview">What this page covers</h2>
        </div>
        <div className="server-detail-answer-card table-surface">
          {config.intro.map((paragraph, index) => (
            <section className="server-detail-answer-section" key={paragraph}>
              <h2>{index === 0 ? `What is ${config.shortName}?` : `How to use this list`}</h2>
              <p>{paragraph}</p>
            </section>
          ))}
        </div>
      </section>

      <ProgrammaticOverviewTable config={config} />
      <ProgrammaticServerTable config={config} data={data} />
      <ProgrammaticConfigBlock data={data} />
      <ProgrammaticFaq config={config} data={data} />
    </main>
  );
}
