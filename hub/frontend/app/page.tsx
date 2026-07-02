import type { Metadata } from "next";

import { ExploreHomeClient } from "@/app/explore-client";
import { PublicHeader } from "@/components/site-header";
import { listPublishedRegistryServerPage } from "@/lib/public-registry";
import { getRegistryFacts } from "@/lib/registry-facts";
import { siteConfig } from "@/lib/site";
import { JsonLdScript, registryIndexJsonLd } from "@/lib/structured-data";

export const revalidate = 3600;
const EXPLORE_PAGE_SIZE = 60;

type HomeProps = {
  searchParams?: Promise<{
    q?: string | string[];
  }>;
};

export const metadata: Metadata = {
  alternates: {
    canonical: "/",
  },
  description: siteConfig.description,
  openGraph: {
    description: siteConfig.description,
    title: `${siteConfig.tagline} | ${siteConfig.name}`,
    url: "/",
  },
  title: siteConfig.tagline,
  twitter: {
    card: "summary",
    description: siteConfig.description,
    title: `${siteConfig.tagline} | ${siteConfig.name}`,
  },
};

function firstSearchParam(value: string | string[] | undefined) {
  if (Array.isArray(value)) return value[0]?.trim() ?? "";
  return value?.trim() ?? "";
}

export default async function Home({ searchParams }: HomeProps) {
  const resolvedSearchParams = await searchParams;
  const searchQuery = firstSearchParam(resolvedSearchParams?.q);
  const [{ error, nextCursor, servers }, registryFacts] = await Promise.all([
    (async () => {
      try {
        const page = await listPublishedRegistryServerPage({
          limit: EXPLORE_PAGE_SIZE,
          search: searchQuery || undefined,
        });
        return {
          error: "",
          nextCursor: page.nextCursor,
          servers: page.servers,
        };
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
      <JsonLdScript data={registryIndexJsonLd(servers)} id="registry-index-json-ld" />
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
