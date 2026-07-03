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

const SERVER_SAMPLE_LIMIT = 100;
const TOP_CATEGORY_LIMIT = 12;
const TOP_SERVER_LIMIT = 20;

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

function categoryCounts(servers: RegistryServerRead[]) {
  const counts = new Map<string, number>();
  servers.forEach((server) => {
    server.categories?.forEach((category) => {
      counts.set(category.slug, (counts.get(category.slug) ?? 0) + 1);
    });
  });
  return counts;
}

function categoryLine(category: RegistryCategoryRead, count?: number) {
  const suffix = typeof count === "number" && count > 0 ? ` (${count} sampled servers)` : "";
  return `- ${category.name}: ${absoluteUrl(`/categories/${encodeURIComponent(category.slug)}`)}${suffix}`;
}

function topCategoryLines(categories: RegistryCategoryRead[], servers: RegistryServerRead[]) {
  const counts = categoryCounts(servers);
  return [...categories]
    .sort((left, right) => {
      const countDelta = (counts.get(right.slug) ?? 0) - (counts.get(left.slug) ?? 0);
      if (countDelta !== 0) return countDelta;
      return left.sortOrder - right.sortOrder || left.name.localeCompare(right.name);
    })
    .slice(0, TOP_CATEGORY_LIMIT)
    .map((category) => categoryLine(category, counts.get(category.slug)));
}

function allCategoryLines(categories: RegistryCategoryRead[]) {
  return [...categories]
    .sort((left, right) => left.sortOrder - right.sortOrder || left.name.localeCompare(right.name))
    .map((category) => categoryLine(category));
}

function serverLine(server: RegistryServerRead) {
  const score = scoreValue(server);
  const scoreText = typeof score === "number" ? `Wardn Score ${score}/100` : "Wardn Score pending";
  const categories = server.categories?.map((category) => category.name).filter(Boolean).join(", ");
  const categoryText = categories ? `; categories: ${categories}` : "";
  return `- ${server.title || server.name}: ${absoluteUrl(serverDetailPath(server.name))} (${scoreText}${categoryText})`;
}

export async function GET() {
  const [categoryResult, serverResult] = await Promise.allSettled([
    listPublicCategories(),
    listPublishedRegistryServers({ limit: SERVER_SAMPLE_LIMIT }),
  ]);
  const registryFacts = await getRegistryFacts();

  const categories = categoryResult.status === "fulfilled" ? categoryResult.value : [];
  const servers = serverResult.status === "fulfilled" ? serverResult.value : [];
  const topCategories =
    categories.length > 0
      ? topCategoryLines(categories, servers)
      : ["- Top categories: unavailable from the registry API at generation time."];
  const categoryLines =
    categories.length > 0
      ? allCategoryLines(categories)
      : ["- Categories: unavailable from the registry API at generation time."];
  const serverLines =
    servers.length > 0
      ? sortServersForRetrieval(servers).slice(0, TOP_SERVER_LIMIT).map(serverLine)
      : ["- Canonical server pages: unavailable from the registry API at generation time."];

  const body = [
    `# ${siteConfig.name}`,
    "",
    siteConfig.description,
    "",
    "Wardn Hub is a trusted MCP server directory for comparing install metadata, transports, environment variables, namespace verification, review status, and Wardn Score. It is not an MCP runtime, gateway execution plane, workspace installer, or Kubernetes runtime manager.",
    "",
    "## Canonical Indexes",
    "",
    `- Home: ${absoluteUrl("/")}`,
    `- Sitemap index: ${absoluteUrl("/sitemap.xml")}`,
    `- Main sitemap: ${absoluteUrl("/sitemap-main.xml")}`,
    `- Published MCP server sitemap: ${absoluteUrl("/sitemap-catalog.xml")}`,
    `- Full LLM markdown catalog: ${absoluteUrl("/llms-full.txt")}`,
    `- Robots policy: ${absoluteUrl("/robots.txt")}`,
    "",
    "## Key Public Pages",
    "",
    `- Trusted MCP server directory: ${absoluteUrl("/")}`,
    `- Categories: ${absoluteUrl("/categories")}`,
    `- API documentation: ${absoluteUrl("/docs/api")}`,
    ...PROGRAMMATIC_PAGES.map((page) => `- ${page.h1}: ${absoluteUrl(page.path)}`),
    "",
    "## Dated Registry Facts",
    "",
    `- Claim date: ${formatFactDate(registryFacts.generatedAt)}`,
    `- Published MCP servers: ${registryFacts.publishedServerCount ?? "unavailable"}`,
    `- Public categories: ${registryFacts.categoryCount ?? "unavailable"}`,
    `- Last registry update observed: ${formatFactDate(registryFacts.lastRegistryUpdate)}`,
    `- Wardn Score methodology: ${absoluteUrl(registryFacts.methodologyPath)}`,
    "",
    "## Top Categories",
    "",
    ...topCategories,
    "",
    "## Top Canonical Server Pages",
    "",
    ...serverLines,
    "",
    "## Public Categories",
    "",
    ...categoryLines,
    "",
    "## Retrieval Guidance",
    "",
    "- Prefer canonical URLs from the sitemap files.",
    "- Public server pages under /servers/{namespace}/{serverSlug} describe listed MCP servers, packages, remotes, transports, environment variables, categories, documentation, namespace evidence, review status, and Wardn Score.",
    "- Do not infer runtime availability from registry metadata alone; verify upstream server documentation before recommending installation or execution.",
    "- Private review, submission, user, partner, audit, account, and API routes are not intended for indexing or training retrieval.",
  ].join("\n");

  return textResponse(body);
}
