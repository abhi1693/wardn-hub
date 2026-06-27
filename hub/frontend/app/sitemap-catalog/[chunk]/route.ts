import { catalogSitemapResponse } from "@/lib/catalog-sitemap";
import { sitemapUnavailableResponse } from "@/lib/sitemap";

export const revalidate = 3600;
export const dynamic = "force-dynamic";

type CatalogSitemapChunkRouteProps = {
  params: Promise<{ chunk?: string }>;
};

export async function GET(_request: Request, { params }: CatalogSitemapChunkRouteProps) {
  const { chunk = "" } = await params;
  const chunkIndex = Number(chunk);

  if (!Number.isInteger(chunkIndex) || chunkIndex < 0) {
    return sitemapUnavailableResponse(`Invalid catalog sitemap chunk: ${chunk}`, null);
  }

  return catalogSitemapResponse(chunkIndex);
}
