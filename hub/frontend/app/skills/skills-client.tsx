"use client";

import {
  BadgeCheck,
  CircleDashed,
  Globe2,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  UsersRound,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { InfiniteScrollTrigger } from "@/components/infinite-scroll-trigger";
import type { SkillPagination, SkillRead } from "@/lib/api/generated/model";
import { SKILLS_PAGE_SIZE } from "@/lib/public-listing-limits";
import { listPublicSkillsPage } from "@/lib/public-skills";
import { SkillLeaderboard } from "./skills-ui";

const SEARCH_DEBOUNCE_MS = 250;
type SkillAuditFilter = "fail" | "pass" | "unaudited" | "warn";
type SkillView = "all-time" | "hot" | "trending";
const SKILL_VIEW_PATHS: Record<SkillView, string> = {
  "all-time": "/skills",
  hot: "/skills/hot",
  trending: "/skills/trending",
};
type SkillFilterOption<T extends string> = {
  icon: LucideIcon;
  label: string;
  value: T;
};
const SKILL_AUDIT_FILTER_OPTIONS: Array<SkillFilterOption<SkillAuditFilter | "">> = [
  { icon: Shield, label: "All", value: "" },
  { icon: ShieldCheck, label: "Passed", value: "pass" },
  { icon: ShieldAlert, label: "Review", value: "warn" },
  { icon: ShieldX, label: "Failed", value: "fail" },
  { icon: CircleDashed, label: "Unaudited", value: "unaudited" },
];
type SkillOfficialFilter = "" | "false" | "true";
const SKILL_OFFICIAL_FILTER_OPTIONS: Array<SkillFilterOption<SkillOfficialFilter>> = [
  { icon: Globe2, label: "All", value: "" },
  { icon: BadgeCheck, label: "Official", value: "true" },
  { icon: UsersRound, label: "Community", value: "false" },
];
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

function sourceFilterLabel(value: SkillOfficialFilter) {
  if (value === "true") return "Official skills";
  if (value === "false") return "Community skills";
  return "All skills";
}

function SkillsFilterGroup<T extends string>({
  label,
  onChange,
  options,
  value,
}: {
  label: string;
  onChange: (value: T) => void;
  options: Array<SkillFilterOption<T>>;
  value: T;
}) {
  return (
    <div className="skills-filter-group">
      <h2>{label}</h2>
      <div className="skills-filter-options">
        {options.map((option) => {
          const Icon = option.icon;
          return (
            <button
              aria-pressed={value === option.value}
              key={option.value || "all"}
              onClick={() => onChange(option.value)}
              type="button"
            >
              <Icon aria-hidden="true" size={14} />
              <span>{option.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function SkillsClient({
  initialError,
  initialAuditStatus,
  initialOfficial,
  initialPagination,
  initialQuery,
  initialSkills,
  initialView,
}: {
  initialError: string;
  initialAuditStatus?: SkillAuditFilter;
  initialOfficial?: boolean;
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
  const [query, setQuery] = useState(initialSearchQuery);
  const [auditStatus, setAuditStatus] = useState<SkillAuditFilter | "">(initialAuditStatus ?? "");
  const [official, setOfficial] = useState<SkillOfficialFilter>(
    initialOfficial === undefined ? "" : String(initialOfficial) as SkillOfficialFilter,
  );
  const [skills, setSkills] = useState<SkillRead[]>(initialSkills);
  const [pagination, setPagination] = useState<SkillPagination>(initialPagination);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(initialError);
  const trimmedQuery = query.trim();
  const hasSearchQuery = trimmedQuery.length > 0;
  const hasMore = pagination.hasMore;
  const resultSummaryTitle = sourceFilterLabel(official);
  const resultSummaryDetail = `${pagination.total.toLocaleString("en-US")} ${
    pagination.total === 1 ? "result" : "results"
  }`;

  const updateQuery = useCallback((nextQuery: string) => {
    latestRequestId.current += 1;
    setQuery(nextQuery);
    setError("");
    setLoading(true);
  }, []);

  const updateAuditStatus = useCallback((nextAuditStatus: SkillAuditFilter | "") => {
    latestRequestId.current += 1;
    setAuditStatus(nextAuditStatus);
    setError("");
    setLoading(true);
  }, []);

  const updateOfficial = useCallback((nextOfficial: SkillOfficialFilter) => {
    latestRequestId.current += 1;
    setOfficial(nextOfficial);
    setError("");
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
    if (auditStatus) {
      url.searchParams.set("audit_status", auditStatus);
    } else {
      url.searchParams.delete("audit_status");
    }
    if (official) {
      url.searchParams.set("official", official);
    } else {
      url.searchParams.delete("official");
    }
    window.history.replaceState(
      window.history.state,
      "",
      `${url.pathname}${url.search}${url.hash}`,
    );
  }, [auditStatus, hasSearchQuery, official, trimmedQuery]);

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
            auditStatus: auditStatus || undefined,
            limit: SKILLS_PAGE_SIZE,
            official: official ? official === "true" : undefined,
            query: hasSearchQuery ? trimmedQuery : undefined,
            view: initialView,
          });
          if (latestRequestId.current !== requestId) return;
          setSkills(response.skills);
          setPagination(response.pagination);
        } catch (caught) {
          if (latestRequestId.current !== requestId) return;
          setError(caught instanceof Error ? caught.message : "Unable to load skills.");
          setSkills([]);
          setPagination(EMPTY_SKILLS_PAGINATION);
        } finally {
          if (latestRequestId.current === requestId) setLoading(false);
        }
      })();
    }, SEARCH_DEBOUNCE_MS);

    return () => window.clearTimeout(timeoutId);
  }, [auditStatus, hasSearchQuery, initialView, official, trimmedQuery]);

  const loadMore = useCallback(async () => {
    if (!hasMore || loading) return;

    const requestId = latestRequestId.current + 1;
    latestRequestId.current = requestId;
    setLoading(true);
    setError("");
    try {
      const response = await listPublicSkillsPage({
        auditStatus: auditStatus || undefined,
        limit: SKILLS_PAGE_SIZE,
        official: official ? official === "true" : undefined,
        page: pagination.page + 1,
        query: hasSearchQuery ? trimmedQuery : undefined,
        view: initialView,
      });
      if (latestRequestId.current !== requestId) return;
      setSkills((current) => [...current, ...response.skills]);
      setPagination(response.pagination);
    } catch (caught) {
      if (latestRequestId.current !== requestId) return;
      setError(caught instanceof Error ? caught.message : "Unable to load more skills.");
    } finally {
      if (latestRequestId.current === requestId) setLoading(false);
    }
  }, [
    auditStatus,
    hasMore,
    hasSearchQuery,
    initialView,
    loading,
    official,
    pagination.page,
    trimmedQuery,
  ]);

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
        <div className="skills-results-layout">
          <aside className="skills-filter-panel" aria-label="Skill filters">
            <SkillsFilterGroup<SkillOfficialFilter>
              label="Source"
              onChange={updateOfficial}
              options={SKILL_OFFICIAL_FILTER_OPTIONS}
              value={official}
            />
            <SkillsFilterGroup<SkillAuditFilter | "">
              label="Audit"
              onChange={updateAuditStatus}
              options={SKILL_AUDIT_FILTER_OPTIONS}
              value={auditStatus}
            />
          </aside>
          <div className="registry-results-shell">
            <div className="skills-results-toolbar">
              <div className="skills-results-heading">
                <h2>{resultSummaryTitle}</h2>
                <p aria-live="polite">{loading ? "Updating results…" : resultSummaryDetail}</p>
              </div>
              <nav className="skills-view-tabs" aria-label="Skill leaderboard view">
                {(
                  [
                    ["all-time", "All time"],
                    ["trending", "Trending 7d"],
                    ["hot", "Hot 24h"],
                  ] as const
                ).map(([value, label]) => (
                  <Link
                    aria-current={initialView === value ? "page" : undefined}
                    href={{
                      pathname: SKILL_VIEW_PATHS[value],
                      query: {
                        ...(auditStatus ? { audit_status: auditStatus } : {}),
                        ...(official ? { official } : {}),
                        ...(hasSearchQuery ? { q: trimmedQuery } : {}),
                      },
                    }}
                    key={value}
                  >
                    {label}
                  </Link>
                ))}
              </nav>
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
        </div>
      </section>
    </>
  );
}
