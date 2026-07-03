"use client";

import { Search, Server } from "lucide-react";
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
const comparisonRows = [
  {
    criterion: "Install metadata",
    detail: "Package targets, remote endpoints, launch commands, and published versions.",
    link: "/registries/npm",
    linkLabel: "Browse package registries",
  },
  {
    criterion: "Runtime requirements",
    detail: "Transport type, environment variables, command arguments, and endpoint requirements.",
    link: "/transports/stdio",
    linkLabel: "Compare transports",
  },
  {
    criterion: "Trust signals",
    detail: "Namespace verification, review status, source evidence, maintenance notes, and Wardn Score.",
    link: "/methodology/quality-score",
    linkLabel: "Read scoring method",
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
  const visibleServerLinks = initialServers.slice(0, 4);
  const lastUpdatedText = formatFactDate(registryFacts.lastRegistryUpdate);
  const generatedAtText = formatFactDate(registryFacts.generatedAt);

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
            <h1 id="registry-hero-title">Trusted MCP server directory</h1>
            <p>
              Compare MCP servers by install metadata, transports, environment variables,
              namespace verification, review status, and Wardn Score before you install.
            </p>
          </div>
          <div className="registry-hero-tools">
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
                  placeholder="Search servers, packages, transports, namespaces"
                  ref={searchInputRef}
                  type="search"
                  value={query}
                />
              </label>
            </form>
            <nav className="registry-quick-links" aria-label="Registry shortcuts">
              <Link href="/categories">Browse categories</Link>
              <Link href="/registries/npm">NPM packages</Link>
              <Link href="/transports/streamable-http">Remote servers</Link>
              <Link href={registryFacts.methodologyPath}>Wardn Score method</Link>
            </nav>
            <section className="registry-trust-strip" aria-label="Wardn comparison signals">
              <span>
                <strong>Install metadata</strong>
                <small>Packages, remotes, launch commands</small>
              </span>
              <span>
                <strong>Runtime requirements</strong>
                <small>Transports, env vars, arguments</small>
              </span>
              <span>
                <strong>Trust review</strong>
                <small>Namespace evidence, review status, Wardn Score</small>
              </span>
            </section>
          </div>
        </div>
      </section>
      <section className="workspace">
        <div className="home-view simple-home">
          <p className="sr-only">
            As of {formatFactDate(registryFacts.generatedAt)}, Wardn Hub lists{" "}
            {registryFacts.publishedServerCount ?? "an unavailable number of"} published MCP
            servers across {registryFacts.categoryCount ?? "an unavailable number of"} categories.
            Last registry update observed {formatFactDate(registryFacts.lastRegistryUpdate)}.
          </p>

          <section className="registry-seo-panel" aria-labelledby="wardn-definition">
            <div className="registry-seo-definition">
              <span>Directory definition</span>
              <h2 id="wardn-definition">What is Wardn Hub?</h2>
              <p>
                Wardn Hub is a trusted MCP server directory for evaluating Model Context Protocol
                servers before installation. Each listing is built around practical registry
                metadata: install targets, transports, environment variables, namespace evidence,
                review status, and Wardn Score.
              </p>
              <div className="registry-update-line">
                <span>Last updated: {lastUpdatedText}</span>
                <span>Page generated: {generatedAtText}</span>
              </div>
            </div>

            <div className="registry-internal-links" aria-label="Directory shortcuts">
              <Link href="/categories">Browse all categories</Link>
              <Link href="/categories/browser-automation">Browser automation MCP servers</Link>
              <Link href="/transports/streamable-http">Streamable HTTP MCP servers</Link>
              <Link href="/registries/pypi">PyPI MCP servers</Link>
              {visibleServerLinks.map((server) => (
                <Link href={serverDetailPath(server.name)} key={server.id}>
                  {server.title || server.name}
                </Link>
              ))}
            </div>
          </section>

          <section className="registry-comparison-section" aria-labelledby="mcp-comparison">
            <div className="category-section-header">
              <span>Comparison framework</span>
              <h2 id="mcp-comparison">How to compare MCP servers</h2>
              <p>
                A useful MCP directory should expose the details that turn a listing into a safe
                client configuration, not just a name and description.
              </p>
            </div>
            <div className="registry-comparison-table" role="table" aria-label="MCP server comparison criteria">
              <div className="registry-comparison-row header" role="row">
                <span role="columnheader">Criterion</span>
                <span role="columnheader">What to check</span>
                <span role="columnheader">Where to start</span>
              </div>
              {comparisonRows.map((row) => (
                <div className="registry-comparison-row" key={row.criterion} role="row">
                  <strong role="cell">{row.criterion}</strong>
                  <span role="cell">{row.detail}</span>
                  <Link href={row.link} role="cell">
                    {row.linkLabel}
                  </Link>
                </div>
              ))}
            </div>
          </section>

          <section className="registry-home-faq" aria-labelledby="registry-faq">
            <div className="category-section-header">
              <span>FAQ</span>
              <h2 id="registry-faq">Trusted MCP directory questions</h2>
            </div>
            <div className="category-faq-grid">
              {homepageFaqs.map((faq) => (
                <article className="category-faq-item" key={faq.question}>
                  <h3>{faq.question}</h3>
                  <p>{faq.answer}</p>
                </article>
              ))}
            </div>
          </section>

          <div className="registry-results-heading">
            <div>
              <span>{hasSearchQuery ? "Search results" : "Registry"}</span>
              <h2>{hasSearchQuery ? `Results for "${trimmedQuery}"` : "Trusted MCP server listings"}</h2>
            </div>
            <Link href="/categories">View categories</Link>
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
        </div>
      </section>
    </>
  );
}
