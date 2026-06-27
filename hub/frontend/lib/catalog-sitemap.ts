import {
  listPublishedRegistryServerSitemapChunk,
  serverDetailPath,
} from "@/lib/public-registry";
import { absoluteUrl } from "@/lib/site";
import {
  sitemapResponse,
  sitemapUnavailableResponse,
  urlsetXml,
  type SitemapUrlEntry,
} from "@/lib/sitemap";

export async function catalogSitemapResponse(chunkIndex: number) {
  try {
    const servers = await listPublishedRegistryServerSitemapChunk(chunkIndex);
    const entries: SitemapUrlEntry[] = servers.map((server) => ({
      changefreq: "weekly" as const,
      lastmod: server.updatedAt,
      loc: absoluteUrl(serverDetailPath(server.name)),
      priority: 0.8,
    }));

    return sitemapResponse(urlsetXml(entries));
  } catch (error) {
    return sitemapUnavailableResponse(
      `Unable to build catalog sitemap chunk ${chunkIndex}.`,
      error,
    );
  }
}
