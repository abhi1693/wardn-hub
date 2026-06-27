import { catalogSitemapResponse } from "@/lib/catalog-sitemap";
import {
  countPublishedRegistryServers,
  SITEMAP_CATALOG_CHUNK_SIZE,
} from "@/lib/public-registry";
import { sitemapUnavailableResponse } from "@/lib/sitemap";

export const revalidate = 3600;

type CatalogSitemapChunkRouteProps = {
  params: Promise<{ chunk?: string }>;
};

export async function generateStaticParams() {
  try {
    const serverCount = await countPublishedRegistryServers();
    const chunkCount = Math.ceil(serverCount / SITEMAP_CATALOG_CHUNK_SIZE);
    return Array.from({ length: chunkCount }, (_, chunk) => ({ chunk: String(chunk) }));
  } catch (error) {
    console.error("Unable to prebuild catalog sitemap chunks from the registry API.", error);
    return [];
  }
}

export async function GET(_request: Request, { params }: CatalogSitemapChunkRouteProps) {
  const { chunk = "" } = await params;
  const chunkIndex = Number(chunk);

  if (!Number.isInteger(chunkIndex) || chunkIndex < 0) {
    return sitemapUnavailableResponse(`Invalid catalog sitemap chunk: ${chunk}`, null);
  }

  return catalogSitemapResponse(chunkIndex);
}
