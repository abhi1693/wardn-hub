import { catalogSitemapResponse } from "@/lib/catalog-sitemap";

export const revalidate = 3600;

export async function GET() {
  return catalogSitemapResponse(0);
}
