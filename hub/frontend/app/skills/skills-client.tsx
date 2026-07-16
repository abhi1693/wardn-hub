"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { InfiniteScrollTrigger } from "@/components/infinite-scroll-trigger";
import type { SkillPagination, SkillRead } from "@/lib/api/generated/model";
import { SKILLS_PAGE_SIZE } from "@/lib/public-listing-limits";
import { listPublicSkillsPage } from "@/lib/public-skills";
import { SkillLeaderboard } from "./skills-ui";

const SEARCH_DEBOUNCE_MS = 250;
type SkillView = "all-time" | "hot" | "trending";
const EMPTY_SKILLS_PAGINATION: SkillPagination = {
  hasMore: false,
  page: 0,
  perPage: SKILLS_PAGE_SIZE,
  total: 0,
};

function EmptyState({ detail, title }: { detail?: string; title: string }) {
  return (
    <div className="empty-state">
      <div className="empty-title">{title}</div>
      {detail ? <div className="empty-detail">{detail}</div> : null}
    </div>
  );
}

export function SkillsClient({
  initialError,
  initialPagination,
  initialQuery,
  initialSkills,
  initialView,
}: {
  initialError: string;
  initialPagination: SkillPagination;
  initialQuery: string;
  initialSkills: SkillRead[];
  initialView: SkillView;
}) {
  const searchInputId = useId();
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const didMountRef = useRef(false);
  const latestRequestId = useRef(0);
  const initialSearchQuery = initialQuery.trim();
  const hasInitialSearchQuery = initialSearchQuery.length > 0;
  const hasBaseSkillsRef = useRef(!hasInitialSearchQuery);
  const [query, setQuery] = useState(initialSearchQuery);
  const [baseSkills, setBaseSkills] = useState(hasInitialSearchQuery ? [] : initialSkills);
  const [basePagination, setBasePagination] = useState<SkillPagination>(
    hasInitialSearchQuery ? EMPTY_SKILLS_PAGINATION : initialPagination,
  );
  const [searchSkills, setSearchSkills] = useState<SkillRead[]>(
    hasInitialSearchQuery ? initialSkills : [],
  );
  const [searchPagination, setSearchPagination] = useState<SkillPagination>(
    hasInitialSearchQuery ? initialPagination : EMPTY_SKILLS_PAGINATION,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(initialError);
  const trimmedQuery = query.trim();
  const hasSearchQuery = trimmedQuery.length > 0;
  const skills = hasSearchQuery ? searchSkills : baseSkills;
  const pagination = hasSearchQuery ? searchPagination : basePagination;
  const hasMore = pagination.hasMore;
  const resultLabel = `${pagination.total.toLocaleString("en-US")} ${
    pagination.total === 1 ? "skill" : "skills"
  }`;

  const updateQuery = useCallback((nextQuery: string) => {
    latestRequestId.current += 1;
    setQuery(nextQuery);
    setError("");
    if (!nextQuery.trim() && hasBaseSkillsRef.current) {
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
    if (!hasSearchQuery && hasBaseSkillsRef.current) return undefined;

    const requestId = latestRequestId.current + 1;
    latestRequestId.current = requestId;

    const timeoutId = window.setTimeout(() => {
      setError("");
      setLoading(true);

      void (async () => {
        try {
          const response = await listPublicSkillsPage({
            limit: SKILLS_PAGE_SIZE,
            query: hasSearchQuery ? trimmedQuery : undefined,
            view: initialView,
          });
          if (latestRequestId.current !== requestId) return;
          if (hasSearchQuery) {
            setSearchSkills(response.skills);
            setSearchPagination(response.pagination);
          } else {
            setBaseSkills(response.skills);
            setBasePagination(response.pagination);
            hasBaseSkillsRef.current = true;
          }
        } catch (caught) {
          if (latestRequestId.current !== requestId) return;
          setError(caught instanceof Error ? caught.message : "Unable to load skills.");
          if (hasSearchQuery) {
            setSearchSkills([]);
            setSearchPagination(EMPTY_SKILLS_PAGINATION);
          } else {
            setBaseSkills([]);
            setBasePagination(EMPTY_SKILLS_PAGINATION);
          }
        } finally {
          if (latestRequestId.current === requestId) setLoading(false);
        }
      })();
    }, SEARCH_DEBOUNCE_MS);

    return () => window.clearTimeout(timeoutId);
  }, [hasSearchQuery, initialView, trimmedQuery]);

  const loadMore = useCallback(async () => {
    if (!hasMore || loading) return;

    const requestId = latestRequestId.current + 1;
    latestRequestId.current = requestId;
    setLoading(true);
    setError("");
    try {
      const response = await listPublicSkillsPage({
        limit: SKILLS_PAGE_SIZE,
        page: pagination.page + 1,
        query: hasSearchQuery ? trimmedQuery : undefined,
        view: initialView,
      });
      if (latestRequestId.current !== requestId) return;
      if (hasSearchQuery) {
        setSearchSkills((current) => [...current, ...response.skills]);
        setSearchPagination(response.pagination);
      } else {
        setBaseSkills((current) => [...current, ...response.skills]);
        setBasePagination(response.pagination);
      }
    } catch (caught) {
      if (latestRequestId.current !== requestId) return;
      setError(caught instanceof Error ? caught.message : "Unable to load more skills.");
    } finally {
      if (latestRequestId.current === requestId) setLoading(false);
    }
  }, [hasMore, hasSearchQuery, initialView, loading, pagination.page, trimmedQuery]);

  return (
    <>
      <section className="registry-hero-section" aria-labelledby="skills-title">
        <div className="registry-hero-inner">
          <div className="registry-hero-copy">
            <span className="registry-hero-eyebrow">The open agent skills ecosystem</span>
            <h1 id="skills-title">Skills</h1>
            <p>
              Browse reusable agent skills, inspect published files, and follow trusted sources.
            </p>
            <form
              className="registry-hero-search-form"
              onSubmit={(event) => event.preventDefault()}
              role="search"
            >
              <label className="registry-hero-search" htmlFor={searchInputId}>
                <Search aria-hidden="true" size={22} />
                <span className="sr-only">Search skills</span>
                <input
                  aria-label="Search skills"
                  autoComplete="off"
                  id={searchInputId}
                  name="q"
                  onChange={(event) => updateQuery(event.currentTarget.value)}
                  placeholder="Search skills"
                  ref={searchInputRef}
                  type="search"
                  value={query}
                />
              </label>
            </form>
          </div>
        </div>
      </section>

      <section className="content-section" aria-label="Skills">
        <div className="registry-results-shell">
          <div className="skills-results-toolbar">
            <nav className="skills-view-tabs" aria-label="Skill leaderboard view">
              {(
                [
                  ["all-time", "All time"],
                  ["trending", "Trending · 7d"],
                  ["hot", "Hot · 24h"],
                ] as const
              ).map(([value, label]) => (
                <Link
                  aria-current={initialView === value ? "page" : undefined}
                  href={{
                    pathname: "/skills",
                    query: {
                      ...(hasSearchQuery ? { q: trimmedQuery } : {}),
                      ...(value === "all-time" ? {} : { view: value }),
                    },
                  }}
                  key={value}
                >
                  {label}
                </Link>
              ))}
            </nav>
            <span className="skills-results-count" aria-live="polite">
              {loading ? "Updating…" : resultLabel}
            </span>
          </div>
          {error && skills.length === 0 ? (
            <EmptyState detail={error} title="Unable to load skills" />
          ) : null}
          {!error && loading && skills.length === 0 ? (
            <EmptyState title="Searching skills" />
          ) : null}
          {!error && !loading && skills.length === 0 ? (
            <EmptyState title={hasSearchQuery ? "No matching skills" : "No skills found"} />
          ) : null}
          {skills.length > 0 ? (
            <>
              <SkillLeaderboard skills={skills} />
              <InfiniteScrollTrigger
                error={error}
                hasMore={hasMore}
                loading={loading}
                onLoadMore={loadMore}
              />
            </>
          ) : null}
        </div>
      </section>
    </>
  );
}
