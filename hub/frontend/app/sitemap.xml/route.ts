import { absoluteUrl } from "@/lib/site";
import { sitemapIndexXml, sitemapResponse } from "@/lib/sitemap";

export const revalidate = 3600;

export async function GET() {
  const now = new Date();

  return sitemapResponse(
    sitemapIndexXml([
      { lastmod: now, loc: absoluteUrl("/sitemap-main.xml") },
      { lastmod: now, loc: absoluteUrl("/sitemap-catalog.xml") },
    ]),
  );
}
