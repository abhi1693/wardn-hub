import { listPublicCategories } from "@/lib/public-registry";
import { absoluteUrl, siteConfig } from "@/lib/site";
import { textResponse } from "@/lib/sitemap";

export const revalidate = 3600;
export const dynamic = "force-dynamic";

export async function GET() {
  let categoryLines: string[] = [];

  try {
    const categories = await listPublicCategories();
    categoryLines = categories
      .sort((left, right) => left.sortOrder - right.sortOrder || left.name.localeCompare(right.name))
      .map((category) => `- ${category.name}: ${absoluteUrl(`/categories/${encodeURIComponent(category.slug)}`)}`);
  } catch {
    categoryLines = ["- Categories: unavailable from the registry API at generation time."];
  }

  const body = [
    `# ${siteConfig.name}`,
    "",
    siteConfig.description,
    "",
    "Wardn Hub is a registry and submission product for MCP server definitions. It is not an MCP runtime, gateway execution plane, workspace installer, or Kubernetes runtime manager.",
    "",
    "## Canonical Indexes",
    "",
    `- Home: ${absoluteUrl("/")}`,
    `- Sitemap index: ${absoluteUrl("/sitemap.xml")}`,
    `- Main sitemap: ${absoluteUrl("/sitemap-main.xml")}`,
    `- Published MCP server sitemap: ${absoluteUrl("/sitemap-catalog.xml")}`,
    `- Robots policy: ${absoluteUrl("/robots.txt")}`,
    "",
    "## Key Public Pages",
    "",
    `- Published MCP server registry: ${absoluteUrl("/")}`,
    `- Categories: ${absoluteUrl("/categories")}`,
    "",
    "## Public Categories",
    "",
    ...categoryLines,
    "",
    "## Retrieval Guidance",
    "",
    "- Prefer canonical URLs from the sitemap files.",
    "- Public server pages under /servers/{namespace}/{serverSlug} describe approved MCP server metadata, packages, remotes, categories, and documentation.",
    "- Do not infer runtime availability from registry metadata alone; verify upstream server documentation before recommending installation or execution.",
    "- Private review, submission, user, partner, audit, account, and API routes are not intended for indexing or training retrieval.",
  ].join("\n");

  return textResponse(body);
}
