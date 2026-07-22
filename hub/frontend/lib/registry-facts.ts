import { getPublicRegistryStats } from "@/lib/public-registry";
import {
  QUALITY_SCORE_METHODOLOGY_PATH,
  type RegistryFacts,
} from "@/lib/registry-facts-shared";

export type { RegistryFacts } from "@/lib/registry-facts-shared";

export async function getRegistryFacts(): Promise<RegistryFacts> {
  try {
    const stats = await getPublicRegistryStats();
    return {
      categoryCount: stats.categoryCount,
      generatedAt: stats.generatedAt,
      lastRegistryUpdate: stats.lastRegistryUpdate ?? null,
      methodologyPath: QUALITY_SCORE_METHODOLOGY_PATH,
      publishedServerCount: stats.publishedServerCount,
    };
  } catch {
    return {
      categoryCount: null,
      generatedAt: new Date().toISOString(),
      lastRegistryUpdate: null,
      methodologyPath: QUALITY_SCORE_METHODOLOGY_PATH,
      publishedServerCount: null,
    };
  }
}
