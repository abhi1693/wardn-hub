import type { RegistryServerRead } from "@/lib/api/generated/model";
import {
  listPublicCategories,
  listPublishedRegistryServers,
  SITEMAP_CATALOG_CHUNK_SIZE,
} from "@/lib/public-registry";
import {
  QUALITY_SCORE_METHODOLOGY_PATH,
  type RegistryFacts,
} from "@/lib/registry-facts-shared";

export type { RegistryFacts } from "@/lib/registry-facts-shared";

const UPDATE_SCAN_LIMIT = SITEMAP_CATALOG_CHUNK_SIZE;

function dateValue(value: unknown) {
  if (typeof value !== "string" || !value.trim()) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString();
}

function latestServerDate(servers: RegistryServerRead[]) {
  const dates = servers
    .flatMap((server) => [
      dateValue(server.updatedAt),
      dateValue(server.latestVersion?.publishedAt),
    ])
    .filter(Boolean)
    .sort((left, right) => right.localeCompare(left));
  return dates[0] ?? null;
}

export async function getRegistryFacts(): Promise<RegistryFacts> {
  const generatedAt = new Date().toISOString();
  const [categoryResult, updateResult] = await Promise.allSettled([
    listPublicCategories(),
    listPublishedRegistryServers({ limit: UPDATE_SCAN_LIMIT }),
  ]);

  const updateServers = updateResult.status === "fulfilled" ? updateResult.value : [];

  return {
    categoryCount: categoryResult.status === "fulfilled" ? categoryResult.value.length : null,
    generatedAt,
    lastRegistryUpdate: latestServerDate(updateServers),
    methodologyPath: QUALITY_SCORE_METHODOLOGY_PATH,
    publishedServerCount: updateServers.length > 0 ? updateServers.length : null,
    scannedServerCount: updateServers.length,
  };
}
