"use client";

import { Search } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import type { SkillPagination, SkillRead } from "@/lib/api/generated/model";
import { listPublicSkillsPage } from "@/lib/public-skills";
import { SkillCardGrid } from "./skills-ui";

const SKILLS_PAGE_SIZE = 60;
const SEARCH_DEBOUNCE_MS = 250;
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
}: {
  initialError: string;
  initialPagination: SkillPagination;
  initialQuery: string;
  initialSkills: SkillRead[];
}) {
  const searchInputId = useId();
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const didMountRef = useRef(false);
  const latestRequestId = useRef(0);
  const initialSearchQuery = initialQuery.trim();
  const hasInitialSearchQuery = initialSearchQuery.length > 0;
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

  const updateQuery = useCallback((nextQuery: string) => {
    setQuery(nextQuery);
    if (!nextQuery.trim()) {
      latestRequestId.current += 1;
      setError("");
      setLoading(false);
    }
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
    if (!didMountRef.current) {
      didMountRef.current = true;
      return undefined;
    }

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
          });
          if (latestRequestId.current !== requestId) return;
          if (hasSearchQuery) {
            setSearchSkills(response.skills);
            setSearchPagination(response.pagination);
          } else {
            setBaseSkills(response.skills);
            setBasePagination(response.pagination);
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
  }, [hasSearchQuery, trimmedQuery]);

  async function loadMore() {
    if (!hasMore || loading) return;

    setLoading(true);
    setError("");
    try {
      const response = await listPublicSkillsPage({
        limit: SKILLS_PAGE_SIZE,
        page: pagination.page + 1,
        query: hasSearchQuery ? trimmedQuery : undefined,
      });
      if (hasSearchQuery) {
        setSearchSkills((current) => [...current, ...response.skills]);
        setSearchPagination(response.pagination);
      } else {
        setBaseSkills((current) => [...current, ...response.skills]);
        setBasePagination(response.pagination);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load more skills.");
    } finally {
      setLoading(false);
    }
  }

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
          <div className="registry-results-heading">
            <div>
              <span>{hasSearchQuery ? "Search results" : "Skills"}</span>
              <h2>{hasSearchQuery ? `Results for "${trimmedQuery}"` : "Reusable agent skills"}</h2>
              <p>
                {hasSearchQuery
                  ? "Filtered by skill name, description, source owner, and repository metadata."
                  : "Scan imported skills as cards with their source, summary, and official status."}
              </p>
            </div>
          </div>
          {error ? <EmptyState detail={error} title="Unable to load skills" /> : null}
          {!error && loading ? <EmptyState title="Searching skills" /> : null}
          {!error && !loading && skills.length === 0 ? (
            <EmptyState title={hasSearchQuery ? "No matching skills" : "No skills found"} />
          ) : null}
          {skills.length > 0 ? (
            <>
              <SkillCardGrid skills={skills} />
              {hasMore || error ? (
                <div className="server-grid-more">
                  {error ? <p>{error}</p> : null}
                  {hasMore ? (
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
