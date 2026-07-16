import { listPublicCategories } from "@/lib/public-registry";
import { PROGRAMMATIC_PAGES } from "@/lib/programmatic-pages";
import { absoluteUrl } from "@/lib/site";
import { sitemapResponse, urlsetXml, type SitemapUrlEntry } from "@/lib/sitemap";

export const revalidate = 3600;

export async function GET() {
  const now = new Date();
  const entries: SitemapUrlEntry[] = [
    { changefreq: "daily", lastmod: now, loc: absoluteUrl("/"), priority: 1 },
    { changefreq: "daily", lastmod: now, loc: absoluteUrl("/mcp-servers"), priority: 0.95 },
    { changefreq: "monthly", lastmod: now, loc: absoluteUrl("/advertise"), priority: 0.6 },
    { changefreq: "weekly", lastmod: now, loc: absoluteUrl("/categories"), priority: 0.8 },
    { changefreq: "monthly", lastmod: now, loc: absoluteUrl("/docs/api"), priority: 0.75 },
    { changefreq: "daily", lastmod: now, loc: absoluteUrl("/skills"), priority: 0.85 },
    { changefreq: "daily", lastmod: now, loc: absoluteUrl("/skills/trending"), priority: 0.8 },
    { changefreq: "daily", lastmod: now, loc: absoluteUrl("/skills/hot"), priority: 0.8 },
    { changefreq: "weekly", lastmod: now, loc: absoluteUrl("/skills/official"), priority: 0.7 },
    {
      changefreq: "monthly",
      lastmod: now,
      loc: absoluteUrl("/methodology/quality-score"),
      priority: 0.7,
    },
    ...PROGRAMMATIC_PAGES.map((page) => ({
      changefreq: "weekly" as const,
      lastmod: now,
      loc: absoluteUrl(page.path),
      priority: 0.75,
    })),
  ];

  try {
    const categories = await listPublicCategories();
    entries.push(
      ...categories.map((category) => ({
        changefreq: "weekly" as const,
        lastmod: now,
        loc: absoluteUrl(`/categories/${encodeURIComponent(category.slug)}`),
        priority: 0.7,
      })),
    );
  } catch (error) {
    // Keep the core sitemap valid even if the registry API is temporarily unavailable.
    console.error("Unable to add category URLs to sitemap-main.xml.", error);
  }

  return sitemapResponse(urlsetXml(entries));
}
