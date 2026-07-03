"use client";

import {
  ArrowRight,
  Clock3,
  Database,
  Network,
  PackageCheck,
  Search,
  Server,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { ServerCard } from "@/components/server-card";
import { listPublishedServers } from "@/lib/api/hub";
import type { RegistryServerRead } from "@/lib/api/generated/model";
import { serverDetailPath } from "@/lib/public-registry";
import { PUBLIC_CARD_FIELDS } from "@/lib/registry-fields";
import type { RegistryFacts } from "@/lib/registry-facts-shared";
import { formatFactDate } from "@/lib/registry-facts-shared";

const EXPLORE_PAGE_SIZE = 60;
const SEARCH_DEBOUNCE_MS = 250;
const directorySignals = [
  {
    detail: "Package targets, remote endpoints, launch commands, and version metadata.",
    icon: PackageCheck,
    title: "Install shape",
  },
  {
    detail: "Transport type, environment variables, arguments, and auth requirements.",
    icon: Network,
    title: "Runtime surface",
  },
  {
    detail: "Namespace evidence, review status, source links, and Wardn Score.",
    icon: ShieldCheck,
    title: "Review signals",
  },
];
const homepageFaqs = [
  {
    answer:
      "Wardn Hub is a trusted MCP server directory. It helps developers compare Model Context Protocol servers by installation metadata, transports, environment variables, namespace verification, review status, and Wardn Score before adding a server to an MCP client.",
    question: "What is Wardn Hub?",
  },
  {
    answer:
      "Start with servers that publish clear package or remote metadata, documented environment variables, current source links, and a strong Wardn Score. Then verify upstream documentation before installing or connecting sensitive accounts.",
    question: "How should I choose an MCP server?",
  },
  {
    answer:
      "No. Wardn Hub is a registry and discovery product, not an MCP runtime or gateway. It lists metadata, trust signals, and links so operators can evaluate a server before runtime use.",
    question: "Does Wardn Hub run MCP servers?",
  },
];

function formatCount(value: number | null, fallback: string) {
  if (typeof value !== "number") return fallback;
  return new Intl.NumberFormat("en").format(value);
}

function EmptyState({ title, detail }: { detail: string; title: string }) {
  return (
    <div className="empty-state">
      <div className="empty-title">{title}</div>
      <div className="empty-detail">{detail}</div>
    </div>
  );
}

function EmptyServerCard({
  detail,
  title,
}: {
  detail: string;
  title: string;
}) {
  return (
    <div className="server-grid">
      <article className="server-card empty-server-card">
        <span className="server-card-head">
          <span className="server-card-icon">
            <Server size={22} />
          </span>
          <span>
            <strong>{title}</strong>
            <small>Registry</small>
          </span>
        </span>
        <span className="server-card-description">{detail}</span>
      </article>
    </div>
  );
}

export function ExploreHomeClient({
  initialError,
  initialNextCursor,
  initialQuery,
  registryFacts,
  initialServers,
}: {
  initialError: string;
  initialNextCursor: string;
  initialQuery: string;
  registryFacts: RegistryFacts;
  initialServers: RegistryServerRead[];
}) {
  const searchInputId = useId();
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const latestRequestId = useRef(0);
  const initialSearchQuery = initialQuery.trim();
  const hasInitialSearchQuery = initialSearchQuery.length > 0;
  const [query, setQuery] = useState(initialSearchQuery);
  const [baseServers, setBaseServers] = useState(hasInitialSearchQuery ? [] : initialServers);
  const [baseNextCursor, setBaseNextCursor] = useState(
    hasInitialSearchQuery ? "" : initialNextCursor,
  );
  const [searchServers, setSearchServers] = useState<RegistryServerRead[]>(
    hasInitialSearchQuery ? initialServers : [],
  );
  const [searchNextCursor, setSearchNextCursor] = useState(
    hasInitialSearchQuery ? initialNextCursor : "",
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(initialError);
  const trimmedQuery = query.trim();
  const hasSearchQuery = trimmedQuery.length > 0;
  const servers = hasSearchQuery ? searchServers : baseServers;
  const nextCursor = hasSearchQuery ? searchNextCursor : baseNextCursor;
  const featuredServerLinks = initialServers.slice(0, 3);
  const lastUpdatedText = formatFactDate(registryFacts.lastRegistryUpdate);
  const generatedAtText = formatFactDate(registryFacts.generatedAt);
  const publishedCountText = formatCount(registryFacts.publishedServerCount, "Live");
  const categoryCountText = formatCount(registryFacts.categoryCount, "Curated");

  const updateQuery = useCallback((nextQuery: string) => {
    setQuery(nextQuery);
    if (!nextQuery.trim()) {
      latestRequestId.current += 1;
      setError(initialError);
      setLoading(false);
    }
  }, [initialError]);

  useEffect(() => {
    function focusSearch(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchInputRef.current?.focus();
      }
    }

    document.addEventListener("keydown", focusSearch);
    return () => document.removeEventListener("keydown", focusSearch);
  }, []);

  useEffect(() => {
    const input = searchInputRef.current;
    if (!input) return undefined;

    function handleInput(event: Event) {
      updateQuery((event.currentTarget as HTMLInputElement).value);
    }

    input.addEventListener("input", handleInput);
    return () => input.removeEventListener("input", handleInput);
  }, [updateQuery]);

  useEffect(() => {
    if (initialError || !hasSearchQuery) return undefined;

    const requestId = latestRequestId.current + 1;
    latestRequestId.current = requestId;

    const timeoutId = window.setTimeout(() => {
      setError("");
      setLoading(true);

      void (async () => {
        try {
          const response = await listPublishedServers({
            fields: PUBLIC_CARD_FIELDS,
            limit: EXPLORE_PAGE_SIZE,
            search: trimmedQuery,
          });
          if (latestRequestId.current !== requestId) return;
          setSearchServers(response.servers);
          setSearchNextCursor(response.metadata.nextCursor ?? "");
        } catch (caught) {
          if (latestRequestId.current !== requestId) return;
          setError(caught instanceof Error ? caught.message : "Unable to search servers.");
          setSearchServers([]);
          setSearchNextCursor("");
        } finally {
          if (latestRequestId.current === requestId) setLoading(false);
        }
      })();
    }, SEARCH_DEBOUNCE_MS);

    return () => window.clearTimeout(timeoutId);
  }, [hasSearchQuery, initialError, trimmedQuery]);

  async function loadMore() {
    if (!nextCursor || loading) return;

    setLoading(true);
    setError("");
    try {
      const response = await listPublishedServers({
        cursor: nextCursor,
        fields: PUBLIC_CARD_FIELDS,
        limit: EXPLORE_PAGE_SIZE,
        search: hasSearchQuery ? trimmedQuery : undefined,
      });
      if (hasSearchQuery) {
        setSearchServers((current) => [...current, ...response.servers]);
        setSearchNextCursor(response.metadata.nextCursor ?? "");
      } else {
        setBaseServers((current) => [...current, ...response.servers]);
        setBaseNextCursor(response.metadata.nextCursor ?? "");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load more servers.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <section className="registry-hero-section" aria-labelledby="registry-hero-title">
        <div className="registry-hero-inner">
          <div className="registry-hero-copy">
            <span className="registry-hero-eyebrow">Model Context Protocol registry</span>
            <h1 id="registry-hero-title">Find MCP servers you can evaluate quickly</h1>
            <p>
              Search published MCP server listings with install targets, remote endpoints,
              environment variables, namespace evidence, and Wardn review signals in one place.
            </p>
            <form action="/" className="registry-hero-search-form" method="get">
              <label className="registry-hero-search" htmlFor={searchInputId}>
                <Search aria-hidden="true" size={22} />
                <span className="sr-only">Search servers</span>
                <input
                  aria-label="Search servers"
                  autoComplete="off"
                  disabled={Boolean(initialError)}
                  id={searchInputId}
                  name="q"
                  onChange={(event) => updateQuery(event.currentTarget.value)}
                  placeholder="Search MCP servers"
                  ref={searchInputRef}
                  type="search"
                  value={query}
                />
              </label>
            </form>
            <nav className="registry-quick-links" aria-label="Registry shortcuts">
              <Link href="/categories">Categories</Link>
              <Link href="/registries/npm">NPM</Link>
              <Link href="/registries/pypi">PyPI</Link>
              <Link href="/transports/streamable-http">Remote servers</Link>
            </nav>
          </div>

          <aside className="registry-hero-panel" aria-label="Registry snapshot">
            <div className="registry-hero-panel-header">
              <span>
                <Database size={18} />
                Registry snapshot
              </span>
              <small>
                <Clock3 size={14} />
                {lastUpdatedText}
              </small>
            </div>
            <div className="registry-hero-stats" aria-label="Registry facts">
              <span>
                <strong>{publishedCountText}</strong>
                <small>Published listings</small>
              </span>
              <span>
                <strong>{categoryCountText}</strong>
                <small>Categories</small>
              </span>
            </div>
            <div className="registry-hero-signal-list">
              {directorySignals.map((signal) => {
                const Icon = signal.icon;
                return (
                  <div key={signal.title}>
                    <Icon aria-hidden="true" size={18} />
                    <span>
                      <strong>{signal.title}</strong>
                      <small>{signal.detail}</small>
                    </span>
                  </div>
                );
              })}
            </div>
            {featuredServerLinks.length > 0 ? (
              <div className="registry-featured-links">
                <span>Recently indexed</span>
                {featuredServerLinks.map((server) => (
                  <Link href={serverDetailPath(server.name)} key={server.id}>
                    {server.title || server.name}
                    <ArrowRight size={14} />
                  </Link>
                ))}
              </div>
            ) : null}
          </aside>
        </div>
      </section>
      <section className="workspace">
        <div className="home-view registry-home">
          <p className="sr-only">
            As of {formatFactDate(registryFacts.generatedAt)}, Wardn Hub lists{" "}
            {registryFacts.publishedServerCount ?? "an unavailable number of"} published MCP
            servers across {registryFacts.categoryCount ?? "an unavailable number of"} categories.
            Last registry update observed {formatFactDate(registryFacts.lastRegistryUpdate)}.
          </p>

          <div className="registry-results-heading">
            <div>
              <span>{hasSearchQuery ? "Search results" : "Registry"}</span>
              <h2>{hasSearchQuery ? `Results for "${trimmedQuery}"` : "Trusted MCP server listings"}</h2>
              <p>
                {hasSearchQuery
                  ? "Filtered by server name, title, description, package, and namespace metadata."
                  : "Scan published listings with their category, summary, and Wardn Score."}
              </p>
            </div>
            <div className="registry-results-meta">
              <span>Generated {generatedAtText}</span>
              <Link href={registryFacts.methodologyPath}>Score method</Link>
            </div>
          </div>
          {error ? <EmptyState detail={error} title="Registry unavailable" /> : null}
          {!error && loading ? <EmptyState detail="Searching published servers." title="Searching" /> : null}
          {!error && !loading && servers.length === 0 ? (
            <EmptyServerCard
              detail={
                hasSearchQuery
                  ? "Try a different server name, title, or description keyword."
                  : "Once community listings are published, this page will show one card per MCP server."
              }
              title={hasSearchQuery ? "No matching MCP servers" : "No MCP servers published yet"}
            />
          ) : null}
          {servers.length > 0 ? (
            <>
              <div className="server-grid">
                {servers.map((server) => (
                  <ServerCard key={server.id} server={server} showQualityScore />
                ))}
              </div>
              {nextCursor || error ? (
                <div className="server-grid-more">
                  {error ? <p>{error}</p> : null}
                  {nextCursor ? (
                    <button
                      className="server-grid-load-more"
                      disabled={loading}
                      onClick={() => void loadMore()}
                    >
                      {loading ? "Loading..." : "Load more"}
                    </button>
                  ) : null}
                </div>
              ) : null}
            </>
          ) : null}

          {!hasSearchQuery ? (
            <section className="registry-support-section" aria-label="Directory guide">
              <article className="registry-definition-panel">
                <span>What Wardn adds</span>
                <h2>More than a list of MCP server names</h2>
                <p>
                  Wardn Hub keeps install metadata, transports, environment variables, namespace
                  evidence, review status, and Wardn Score close to each server listing.
                </p>
                <div className="registry-update-line">
                  <span>Last registry update: {lastUpdatedText}</span>
                  <span>Page generated: {generatedAtText}</span>
                </div>
              </article>
              <article className="registry-faq-panel">
                <span>Common questions</span>
                {homepageFaqs.map((faq) => (
                  <details key={faq.question}>
                    <summary>{faq.question}</summary>
                    <p>{faq.answer}</p>
                  </details>
                ))}
              </article>
            </section>
          ) : null}
        </div>
      </section>
    </>
  );
}
