"use client";

import { Search, Server } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { InfiniteScrollTrigger } from "@/components/infinite-scroll-trigger";
import { ServerCard } from "@/components/server-card";
import { listPublishedServers } from "@/lib/api/hub";
import type { RegistryServerRead } from "@/lib/api/generated/model";
import { EXPLORE_PAGE_SIZE } from "@/lib/public-listing-limits";
import { PUBLIC_CARD_FIELDS } from "@/lib/registry-fields";
import type { RegistryFacts } from "@/lib/registry-facts-shared";
import { formatFactDate } from "@/lib/registry-facts-shared";

const SEARCH_DEBOUNCE_MS = 250;
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
  const didMountRef = useRef(false);
  const latestRequestId = useRef(0);
  const initialSearchQuery = initialQuery.trim();
  const hasInitialSearchQuery = initialSearchQuery.length > 0;
  const hasBaseServersRef = useRef(!hasInitialSearchQuery);
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
  const lastUpdatedText = formatFactDate(registryFacts.lastRegistryUpdate);
  const listedServerCount = hasSearchQuery
    ? servers.length
    : (registryFacts.publishedServerCount ?? servers.length);
  const resultLabel = `${listedServerCount.toLocaleString("en-US")}${
    hasSearchQuery && nextCursor ? "+" : ""
  } ${
    hasSearchQuery
      ? listedServerCount === 1 && !nextCursor
        ? "result"
        : "results"
      : listedServerCount === 1
        ? "server"
        : "servers"
  }`;

  const updateQuery = useCallback((nextQuery: string) => {
    latestRequestId.current += 1;
    setQuery(nextQuery);
    setError("");
    if (!nextQuery.trim() && hasBaseServersRef.current) {
      setLoading(false);
      return;
    }
    setLoading(true);
  }, []);

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
    const url = new URL(window.location.href);
    if (hasSearchQuery) {
      url.searchParams.set("q", trimmedQuery);
    } else {
      url.searchParams.delete("q");
    }
    window.history.replaceState(
      window.history.state,
      "",
      `${url.pathname}${url.search}${url.hash}`,
    );
  }, [hasSearchQuery, trimmedQuery]);

  useEffect(() => {
    if (!didMountRef.current) {
      didMountRef.current = true;
      return undefined;
    }
    if (initialError || (!hasSearchQuery && hasBaseServersRef.current)) return undefined;

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
            search: hasSearchQuery ? trimmedQuery : undefined,
          });
          if (latestRequestId.current !== requestId) return;
          if (hasSearchQuery) {
            setSearchServers(response.servers);
            setSearchNextCursor(response.metadata.nextCursor ?? "");
          } else {
            setBaseServers(response.servers);
            setBaseNextCursor(response.metadata.nextCursor ?? "");
            hasBaseServersRef.current = true;
          }
        } catch (caught) {
          if (latestRequestId.current !== requestId) return;
          setError(caught instanceof Error ? caught.message : "Unable to search servers.");
          if (hasSearchQuery) {
            setSearchServers([]);
            setSearchNextCursor("");
          } else {
            setBaseServers([]);
            setBaseNextCursor("");
          }
        } finally {
          if (latestRequestId.current === requestId) setLoading(false);
        }
      })();
    }, SEARCH_DEBOUNCE_MS);

    return () => window.clearTimeout(timeoutId);
  }, [hasSearchQuery, initialError, trimmedQuery]);

  const loadMore = useCallback(async () => {
    if (!nextCursor || loading) return;

    const requestId = latestRequestId.current + 1;
    latestRequestId.current = requestId;
    setLoading(true);
    setError("");
    try {
      const response = await listPublishedServers({
        cursor: nextCursor,
        fields: PUBLIC_CARD_FIELDS,
        limit: EXPLORE_PAGE_SIZE,
        search: hasSearchQuery ? trimmedQuery : undefined,
      });
      if (latestRequestId.current !== requestId) return;
      if (hasSearchQuery) {
        setSearchServers((current) => [...current, ...response.servers]);
        setSearchNextCursor(response.metadata.nextCursor ?? "");
      } else {
        setBaseServers((current) => [...current, ...response.servers]);
        setBaseNextCursor(response.metadata.nextCursor ?? "");
      }
    } catch (caught) {
      if (latestRequestId.current !== requestId) return;
      setError(caught instanceof Error ? caught.message : "Unable to load more servers.");
    } finally {
      if (latestRequestId.current === requestId) setLoading(false);
    }
  }, [hasSearchQuery, loading, nextCursor, trimmedQuery]);

  return (
    <>
      <section className="registry-hero-section" aria-labelledby="registry-hero-title">
        <div className="registry-hero-inner">
          <div className="registry-hero-copy">
            <span className="registry-hero-eyebrow">Model Context Protocol registry</span>
            <h1 id="registry-hero-title">Find MCP servers you can evaluate quickly</h1>
            <p>
              Compare install targets, remote endpoints, environment variables, namespace
              evidence, and Wardn review signals in one place.
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
        </div>
      </section>
      <section className="workspace">
        <div className="home-view registry-home">
          <p className="sr-only">
            As of {formatFactDate(registryFacts.generatedAt)}, Wardn Hub lists{" "}
            {registryFacts.publishedServerCount ?? "an unavailable number of"} MCP servers across{" "}
            {registryFacts.categoryCount ?? "an unavailable number of"} categories.
            Last registry update observed {formatFactDate(registryFacts.lastRegistryUpdate)}.
          </p>

          <section
            aria-busy={loading}
            aria-label="Server listings"
            className="registry-results-shell"
          >
            <div className="registry-results-toolbar">
              <h2>{hasSearchQuery ? `Results for "${trimmedQuery}"` : "MCP servers"}</h2>
              <span className="registry-results-count" aria-live="polite">
                {loading ? "Updating…" : resultLabel}
              </span>
            </div>
            {error && servers.length === 0 ? (
              <EmptyState detail={error} title="Registry unavailable" />
            ) : null}
            {!error && loading && servers.length === 0 ? (
              <EmptyState detail="Searching MCP servers." title="Searching" />
            ) : null}
            {!error && !loading && servers.length === 0 ? (
              <EmptyServerCard
                detail={
                  hasSearchQuery
                    ? "Try a different server name, title, or description keyword."
                    : "New community listings will appear here."
                }
                title={hasSearchQuery ? "No matching MCP servers" : "No MCP servers yet"}
              />
            ) : null}
            {servers.length > 0 ? (
              <>
                <div className="server-grid">
                  {servers.map((server) => (
                    <ServerCard
                      hideGenericCategory
                      key={server.id}
                      server={server}
                      showQualityScore
                    />
                  ))}
                </div>
                <InfiniteScrollTrigger
                  error={error}
                  hasMore={Boolean(nextCursor)}
                  loading={loading}
                  onLoadMore={loadMore}
                />
              </>
            ) : null}
          </section>

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
