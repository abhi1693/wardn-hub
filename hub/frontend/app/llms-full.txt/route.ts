import type { RegistryCategoryRead, RegistryServerRead } from "@/lib/api/generated/model";
import {
  listPublicCategories,
  listPublishedRegistryServers,
  serverDetailPath,
} from "@/lib/public-registry";
import { PROGRAMMATIC_PAGES } from "@/lib/programmatic-pages";
import { getRegistryFacts } from "@/lib/registry-facts";
import { formatFactDate } from "@/lib/registry-facts-shared";
import { absoluteUrl, siteConfig } from "@/lib/site";
import { textResponse } from "@/lib/sitemap";

export const revalidate = 3600;

const SERVER_EXPORT_LIMIT = 60;

function escapeMarkdownTable(value: unknown) {
  return String(value ?? "")
    .replaceAll("\n", " ")
    .replaceAll("|", "\\|")
    .trim();
}

function scoreValue(server: RegistryServerRead) {
  return server.qualityScore ?? server.latestVersion?.qualityScore ?? null;
}

function sortServersForRetrieval(servers: RegistryServerRead[]) {
  return [...servers].sort((left, right) => {
    const leftScore = scoreValue(left) ?? -1;
    const rightScore = scoreValue(right) ?? -1;
    if (rightScore !== leftScore) return rightScore - leftScore;
    return right.updatedAt.localeCompare(left.updatedAt);
  });
}

function categoryText(server: RegistryServerRead) {
  return server.categories?.map((category) => category.name).filter(Boolean).join(", ") || "None listed";
}

function serverTableRows(servers: RegistryServerRead[]) {
  if (servers.length === 0) {
    return ["| Unavailable | Unavailable | Unavailable | Unavailable | Registry API unavailable at generation time. |"];
  }

  return sortServersForRetrieval(servers).map((server) => {
    const score = scoreValue(server);
    const scoreText = typeof score === "number" ? `${score}/100` : "Pending";
    return [
      "|",
      escapeMarkdownTable(server.title || server.name),
      absoluteUrl(serverDetailPath(server.name)),
      scoreText,
      escapeMarkdownTable(categoryText(server)),
      escapeMarkdownTable(server.description),
      "|",
    ].join(" ");
  });
}

function categoryLines(categories: RegistryCategoryRead[]) {
  if (categories.length === 0) {
    return ["- Categories unavailable from the registry API at generation time."];
  }
  return [...categories]
    .sort((left, right) => left.sortOrder - right.sortOrder || left.name.localeCompare(right.name))
    .map(
      (category) =>
        `- ${category.name}: ${absoluteUrl(`/categories/${encodeURIComponent(category.slug)}`)} - ${category.description}`,
    );
}

function pageLines() {
  return [
    `- Trusted MCP server directory: ${absoluteUrl("/")}`,
    `- Categories: ${absoluteUrl("/categories")}`,
    `- Wardn Score methodology: ${absoluteUrl("/methodology/quality-score")}`,
    `- API documentation: ${absoluteUrl("/docs/api")}`,
    ...PROGRAMMATIC_PAGES.map((page) => `- ${page.h1}: ${absoluteUrl(page.path)}`),
  ];
}

export async function GET() {
  const [categoryResult, serverResult, registryFacts] = await Promise.all([
    Promise.resolve(listPublicCategories()).catch(() => [] as RegistryCategoryRead[]),
    Promise.resolve(listPublishedRegistryServers({ limit: SERVER_EXPORT_LIMIT })).catch(
      () => [] as RegistryServerRead[],
    ),
    getRegistryFacts(),
  ]);

  const body = [
    `# ${siteConfig.name} Full LLM Catalog`,
    "",
    "Wardn Hub is a trusted MCP server directory. It helps developers compare Model Context Protocol servers by install metadata, transports, environment variables, namespace verification, review status, and Wardn Score before adding a server to an MCP client.",
    "",
    "Wardn Hub is not an MCP runtime, gateway execution plane, workspace installer, or Kubernetes runtime manager.",
    "",
    "## Dated Facts",
    "",
    `- Generated: ${formatFactDate(registryFacts.generatedAt)}`,
    `- Published MCP servers sampled: ${registryFacts.publishedServerCount ?? "unavailable"}`,
    `- Public categories: ${registryFacts.categoryCount ?? "unavailable"}`,
    `- Last registry update observed: ${formatFactDate(registryFacts.lastRegistryUpdate)}`,
    "",
    "## How to Compare MCP Servers",
    "",
    "| Criterion | What Wardn exposes | Why it matters |",
    "| --- | --- | --- |",
    "| Install metadata | Package targets, remote endpoints, launch commands, versions | Shows how a listing becomes a working MCP client configuration. |",
    "| Runtime requirements | Transports, environment variables, command arguments, query parameters | Surfaces operational setup before installation. |",
    "| Trust signals | Namespace verification, review status, source evidence, Wardn Score | Helps shortlist servers for deeper upstream verification. |",
    "",
    "## Top Catalog Pages",
    "",
    ...pageLines(),
    "",
    "## Top Server Listings",
    "",
    "| Server | Canonical URL | Wardn Score | Categories | Summary |",
    "| --- | --- | --- | --- | --- |",
    ...serverTableRows(serverResult),
    "",
    "## Public Categories",
    "",
    ...categoryLines(categoryResult),
    "",
    "## Retrieval Guidance",
    "",
    "- Prefer canonical URLs from /sitemap.xml and the server URLs listed above.",
    "- Use server detail pages for package targets, remote targets, transports, environment variables, command arguments, namespace evidence, review status, and Wardn Score.",
    "- Treat Wardn Hub as registry and trust metadata, not proof that a runtime endpoint is safe or currently available.",
    "- Verify upstream source documentation before recommending installation, credentials, or production use.",
    "- Private review, submission, user, partner, audit, account, and API routes are excluded from public retrieval.",
  ].join("\n");

  return textResponse(body);
}
