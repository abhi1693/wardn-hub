const PUBLIC_CONTENT_CACHE_CONTROL = "public, max-age=0, s-maxage=3600, stale-while-revalidate=86400";

type SitemapDate = Date | string;

export type SitemapIndexEntry = {
  lastmod?: SitemapDate | null;
  loc: string;
};

export type SitemapUrlEntry = {
  changefreq?: "always" | "hourly" | "daily" | "weekly" | "monthly" | "yearly" | "never";
  lastmod?: SitemapDate | null;
  loc: string;
  priority?: number | string | null;
};

export function escapeXml(value: unknown) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function formatSitemapDate(value?: SitemapDate | null) {
  if (!value) return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.toISOString();
  }
  return value;
}

export function sitemapResponse(body: string, init?: ResponseInit) {
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/xml; charset=utf-8");
  headers.set("Cache-Control", PUBLIC_CONTENT_CACHE_CONTROL);

  return new Response(body, {
    ...init,
    headers,
  });
}

export function textResponse(body: string, init?: ResponseInit) {
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "text/plain; charset=utf-8");
  headers.set("Cache-Control", PUBLIC_CONTENT_CACHE_CONTROL);

  return new Response(body, {
    ...init,
    headers,
  });
}

export function sitemapIndexXml(entries: readonly SitemapIndexEntry[]) {
  const sitemaps = entries
    .map((entry) => {
      const lastmod = formatSitemapDate(entry.lastmod);
      return [
        "  <sitemap>",
        `    <loc>${escapeXml(entry.loc)}</loc>`,
        lastmod ? `    <lastmod>${escapeXml(lastmod)}</lastmod>` : null,
        "  </sitemap>",
      ]
        .filter(Boolean)
        .join("\n");
    })
    .join("\n");

  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    sitemaps,
    "</sitemapindex>",
  ]
    .filter(Boolean)
    .join("\n");
}

export function urlsetXml(entries: readonly SitemapUrlEntry[]) {
  const urls = entries
    .map((entry) => {
      const lastmod = formatSitemapDate(entry.lastmod);
      const priority =
        entry.priority === null || entry.priority === undefined ? null : String(entry.priority);

      return [
        "  <url>",
        `    <loc>${escapeXml(entry.loc)}</loc>`,
        lastmod ? `    <lastmod>${escapeXml(lastmod)}</lastmod>` : null,
        entry.changefreq ? `    <changefreq>${escapeXml(entry.changefreq)}</changefreq>` : null,
        priority ? `    <priority>${escapeXml(priority)}</priority>` : null,
        "  </url>",
      ]
        .filter(Boolean)
        .join("\n");
    })
    .join("\n");

  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    urls,
    "</urlset>",
  ]
    .filter(Boolean)
    .join("\n");
}
