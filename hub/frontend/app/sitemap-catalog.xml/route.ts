import { listPublishedRegistryServers, serverDetailPath } from "@/lib/public-registry";
import { absoluteUrl } from "@/lib/site";
import { sitemapResponse, urlsetXml, type SitemapUrlEntry } from "@/lib/sitemap";

export const revalidate = 3600;
export const dynamic = "force-dynamic";

export async function GET() {
  let entries: SitemapUrlEntry[] = [];

  try {
    const servers = await listPublishedRegistryServers();
    entries = servers.map((server) => ({
      changefreq: "weekly" as const,
      lastmod: server.updatedAt,
      loc: absoluteUrl(serverDetailPath(server.name)),
      priority: 0.8,
    }));
  } catch {
    entries = [];
  }

  return sitemapResponse(urlsetXml(entries));
}
