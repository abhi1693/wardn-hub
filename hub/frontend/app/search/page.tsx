import type { Metadata } from "next";
import { ArrowRight, CheckCircle2, Layers3, SearchX } from "lucide-react";
import Link from "next/link";

import { SkillCardGrid } from "@/app/skills/skills-ui";
import { CatalogSearchForm } from "@/components/catalog-search-form";
import { ServerCard } from "@/components/server-card";
import { PublicHeader } from "@/components/site-header";
import type { RegistryServerRead, SkillRead } from "@/lib/api/generated/model";
import { listPublishedRegistryServerPage } from "@/lib/public-registry";
import { searchPublicSkillsPage } from "@/lib/public-skills";

export const dynamic = "force-dynamic";

const SEARCH_RESULT_LIMIT = 8;

type SearchPageProps = {
  searchParams?: Promise<{
    q?: string | string[];
  }>;
};

type CatalogSearchState = {
  auditEnabled: boolean;
  serverError: string;
  serverHasMore: boolean;
  servers: RegistryServerRead[];
  skillError: string;
  skillHasMore: boolean;
  skills: SkillRead[];
};

export const metadata: Metadata = {
  alternates: { canonical: "/search" },
  description: "Search MCP servers and reusable agent skills in Wardn Hub.",
  robots: { follow: true, index: false },
  title: "Search",
};

function firstSearchParam(value: string | string[] | undefined) {
  if (Array.isArray(value)) return value[0]?.trim() ?? "";
  return value?.trim() ?? "";
}

function catalogHref(path: "/mcp-servers" | "/skills", query: string) {
  return `${path}?${new URLSearchParams({ q: query }).toString()}`;
}

function resultCount(count: number, hasMore: boolean) {
  return `${count.toLocaleString("en-US")}${hasMore ? "+" : ""}`;
}

async function searchCatalogs(query: string): Promise<CatalogSearchState> {
  const [serverResult, skillResult] = await Promise.all([
    listPublishedRegistryServerPage({ limit: SEARCH_RESULT_LIMIT, search: query })
      .then((page) => ({
        error: "",
        hasMore: Boolean(page.nextCursor),
        servers: page.servers,
      }))
      .catch((caught) => ({
        error: caught instanceof Error ? caught.message : "Unable to search MCP servers.",
        hasMore: false,
        servers: [] as RegistryServerRead[],
      })),
    searchPublicSkillsPage({ limit: SEARCH_RESULT_LIMIT, query })
      .then((page) => ({
        auditEnabled: page.auditEnabled,
        error: "",
        hasMore: page.hasMore,
        skills: page.skills,
      }))
      .catch((caught) => ({
        auditEnabled: false,
        error: caught instanceof Error ? caught.message : "Unable to search agent skills.",
        hasMore: false,
        skills: [] as SkillRead[],
      })),
  ]);

  return {
    auditEnabled: skillResult.auditEnabled,
    serverError: serverResult.error,
    serverHasMore: serverResult.hasMore,
    servers: serverResult.servers,
    skillError: skillResult.error,
    skillHasMore: skillResult.hasMore,
    skills: skillResult.skills,
  };
}

export default async function SearchPage({ searchParams }: SearchPageProps) {
  const resolvedSearchParams = await searchParams;
  const query = firstSearchParam(resolvedSearchParams?.q);
  const canSearch = query.length >= 3;
  const state = canSearch ? await searchCatalogs(query) : null;

  return (
    <main className="site-shell unified-search-page">
      <PublicHeader />

      <section className="unified-search-hero" aria-labelledby="unified-search-title">
        <div className="unified-search-hero-inner">
          <p className="home-section-kicker">Search</p>
          <h1 id="unified-search-title">Search the agent ecosystem</h1>
          <p>Find MCP servers and reusable agent skills with one query.</p>
          <CatalogSearchForm
            className="unified-search-form"
            defaultValue={query}
            id="unified-catalog-search"
          />
        </div>
      </section>

      <div className="unified-search-content">
        {!query ? (
          <div className="unified-search-message">
            <SearchX aria-hidden="true" size={22} />
            <span>Enter a query to search both catalogs.</span>
          </div>
        ) : !state ? (
          <div className="unified-search-message">
            <SearchX aria-hidden="true" size={22} />
            <span>Enter at least 3 characters to search both catalogs.</span>
          </div>
        ) : (
          <section className="unified-search-results" aria-labelledby="unified-results-title">
            <header className="unified-search-results-heading">
              <h2 id="unified-results-title">Results for &ldquo;{query}&rdquo;</h2>
              <p>MCP servers and agent skills matching the same query.</p>
            </header>

            <section className="unified-search-result-section" aria-labelledby="server-results-title">
              <div className="unified-search-result-heading">
                <div>
                  <span className="unified-search-result-icon" aria-hidden="true">
                    <Layers3 size={19} />
                  </span>
                  <h3 id="server-results-title">MCP servers</h3>
                  <span className="unified-search-result-count">
                    {resultCount(state.servers.length, state.serverHasMore)}
                  </span>
                </div>
                <Link className="home-section-link" href={catalogHref("/mcp-servers", query)}>
                  View all server results <ArrowRight aria-hidden="true" size={16} />
                </Link>
              </div>
              {state.serverError ? (
                <div className="unified-search-error">{state.serverError}</div>
              ) : state.servers.length > 0 ? (
                <div className="server-grid">
                  {state.servers.map((server) => (
                    <ServerCard key={server.id} server={server} showQualityScore />
                  ))}
                </div>
              ) : (
                <div className="unified-search-message compact">No MCP servers matched this query.</div>
              )}
            </section>

            <section className="unified-search-result-section" aria-labelledby="skill-results-title">
              <div className="unified-search-result-heading">
                <div>
                  <span className="unified-search-result-icon skill" aria-hidden="true">
                    <CheckCircle2 size={19} />
                  </span>
                  <h3 id="skill-results-title">Agent skills</h3>
                  <span className="unified-search-result-count">
                    {resultCount(state.skills.length, state.skillHasMore)}
                  </span>
                </div>
                <Link className="home-section-link" href={catalogHref("/skills", query)}>
                  View all skill results <ArrowRight aria-hidden="true" size={16} />
                </Link>
              </div>
              {state.skillError ? (
                <div className="unified-search-error">{state.skillError}</div>
              ) : (
                <SkillCardGrid
                  auditEnabled={state.auditEnabled}
                  emptyLabel="No agent skills matched this query."
                  skills={state.skills}
                />
              )}
            </section>
          </section>
        )}
      </div>
    </main>
  );
}
