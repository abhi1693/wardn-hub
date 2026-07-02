"use client";

import { Search, Server } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { ServerCard } from "@/components/server-card";
import { listPublishedServers } from "@/lib/api/hub";
import type { RegistryServerRead } from "@/lib/api/generated/model";
import { PUBLIC_CARD_FIELDS } from "@/lib/registry-fields";
import type { RegistryFacts } from "@/lib/registry-facts-shared";
import { formatFactDate } from "@/lib/registry-facts-shared";

const EXPLORE_PAGE_SIZE = 60;
const SEARCH_DEBOUNCE_MS = 250;

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
          <h1 id="registry-hero-title">Find the perfect MCP server for your workflow.</h1>
          <p>
            A curated registry of Model Context Protocol servers. Enhance your AI with localized
            knowledge and specialized tools.
          </p>
          <div className="registry-facts" aria-label="Dated registry facts">
            <span>
              As of {formatFactDate(registryFacts.generatedAt)}, Wardn Hub lists{" "}
              <strong>{registryFacts.publishedServerCount ?? "an unavailable number of"}</strong>{" "}
              published MCP servers across{" "}
              <strong>{registryFacts.categoryCount ?? "an unavailable number of"}</strong>{" "}
              categories.
            </span>
            <span>
              Last registry update observed:{" "}
              <strong>{formatFactDate(registryFacts.lastRegistryUpdate)}</strong>.
            </span>
            <a href={registryFacts.methodologyPath}>Wardn Score methodology</a>
          </div>
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
                placeholder="Search servers..."
                ref={searchInputRef}
                type="search"
                value={query}
              />
            </label>
          </form>
        </div>
      </section>
      <section className="workspace">
        <div className="home-view simple-home">
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
        </div>
      </section>
    </>
  );
}
