import { catalogSitemapResponse } from "@/lib/catalog-sitemap";

export const revalidate = 3600;
export const dynamic = "force-dynamic";

export async function GET() {
  return catalogSitemapResponse(0);
}
