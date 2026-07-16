import type { Metadata } from "next";

import { ExploreHomeClient } from "@/app/explore-client";
import { PublicHeader } from "@/components/site-header";
import { listPublishedRegistryServerPage } from "@/lib/public-registry";
import { EXPLORE_PAGE_SIZE } from "@/lib/public-listing-limits";
import { getRegistryFacts } from "@/lib/registry-facts";
import { siteConfig } from "@/lib/site";
import { JsonLdScript, registryIndexJsonLd } from "@/lib/structured-data";

export const revalidate = 3600;

type McpServersPageProps = {
  searchParams?: Promise<{
    q?: string | string[];
  }>;
};

export const metadata: Metadata = {
  alternates: { canonical: "/mcp-servers" },
  description: siteConfig.description,
  openGraph: {
    description: siteConfig.description,
    title: `MCP Servers | ${siteConfig.name}`,
    url: "/mcp-servers",
  },
  title: "MCP Servers",
  twitter: {
    card: "summary_large_image",
    description: siteConfig.description,
    title: `MCP Servers | ${siteConfig.name}`,
  },
};

function firstSearchParam(value: string | string[] | undefined) {
  if (Array.isArray(value)) return value[0]?.trim() ?? "";
  return value?.trim() ?? "";
}

export default async function McpServersPage({ searchParams }: McpServersPageProps) {
  const resolvedSearchParams = await searchParams;
  const searchQuery = firstSearchParam(resolvedSearchParams?.q);
  const [{ error, nextCursor, servers }, registryFacts] = await Promise.all([
    (async () => {
      try {
        const page = await listPublishedRegistryServerPage({
          limit: EXPLORE_PAGE_SIZE,
          search: searchQuery || undefined,
        });
        return { error: "", nextCursor: page.nextCursor, servers: page.servers };
      } catch (caught) {
        return {
          error: caught instanceof Error ? caught.message : "Unable to load registry.",
          nextCursor: "",
          servers: [],
        };
      }
    })(),
    getRegistryFacts(),
  ]);

  return (
    <main className="site-shell">
      <JsonLdScript
        data={registryIndexJsonLd(servers, "/mcp-servers")}
        id="registry-index-json-ld"
      />
      <PublicHeader />
      <ExploreHomeClient
        initialError={error}
        initialNextCursor={nextCursor}
        initialQuery={searchQuery}
        initialServers={servers}
        registryFacts={registryFacts}
      />
    </main>
  );
}
