import {
  countPublishedRegistryServers,
  SITEMAP_CATALOG_CHUNK_SIZE,
} from "@/lib/public-registry";
import { absoluteUrl } from "@/lib/site";
import { sitemapIndexXml, sitemapResponse, sitemapUnavailableResponse } from "@/lib/sitemap";

export const revalidate = 3600;

export async function GET() {
  const now = new Date();
  let catalogChunks = 0;

  try {
    const serverCount = await countPublishedRegistryServers();
    catalogChunks = Math.ceil(serverCount / SITEMAP_CATALOG_CHUNK_SIZE);
  } catch (error) {
    return sitemapUnavailableResponse("Unable to build sitemap index from registry catalog.", error);
  }

  return sitemapResponse(
    sitemapIndexXml([
      { lastmod: now, loc: absoluteUrl("/sitemap-main.xml") },
      ...Array.from({ length: catalogChunks }, (_, index) => ({
        lastmod: now,
        loc: absoluteUrl(`/sitemap-catalog/${index}`),
      })),
    ]),
  );
}
