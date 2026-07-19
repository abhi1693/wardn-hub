"use client";

import * as Dialog from "@radix-ui/react-dialog";
import {
  BadgeCheck,
  CircleDashed,
  GitBranch,
  Globe2,
  Loader2,
  PackagePlus,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  UsersRound,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import type { FormEvent } from "react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { InfiniteScrollTrigger } from "@/components/infinite-scroll-trigger";
import type { SkillPagination, SkillRead } from "@/lib/api/generated/model";
import { SKILLS_PAGE_SIZE } from "@/lib/public-listing-limits";
import {
  importPublicGitHubSkill,
  listPublicSkillsPage,
  searchPublicSkillsPage,
} from "@/lib/public-skills";
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

function RequestSkillDialog({ onImported }: { onImported: () => void }) {
  const inputId = useId();
  const tooltipId = useId();
  const [open, setOpen] = useState(false);
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const trimmedRepositoryUrl = repositoryUrl.trim();

  const validRepositoryUrl =
    /^https:\/\/(www\.)?github\.com\/[A-Za-z0-9-]+\/[A-Za-z0-9_.-]+(?:\/(?:tree|blob)\/[^?#]+)?\/?$/.test(
      trimmedRepositoryUrl,
    );

  async function submitRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSuccess("");
    if (!validRepositoryUrl) {
      setError(
        "Enter a GitHub repository or subfolder URL, for example https://github.com/owner/repository/tree/main/skills/example.",
      );
      return;
    }
    setSubmitting(true);
    try {
      const response = await importPublicGitHubSkill(trimmedRepositoryUrl);
      setSuccess(
        `Imported ${response.importedSkillCount.toLocaleString("en-US")} ${
          response.importedSkillCount === 1 ? "skill" : "skills"
        } from ${response.source}.`,
      );
      setRepositoryUrl("");
      onImported();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to import this repository.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog.Root
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (nextOpen) return;
        setError("");
        setSuccess("");
        setSubmitting(false);
      }}
      open={open}
    >
      <div className="skills-request-card">
        <Dialog.Trigger asChild>
          <button
            aria-describedby={tooltipId}
            aria-label="Request a Skill"
            className="skills-request-trigger"
            type="button"
          >
            <PackagePlus aria-hidden="true" size={16} />
            <span>Request a Skill</span>
          </button>
        </Dialog.Trigger>
        <span className="skills-request-tooltip" id={tooltipId} role="tooltip">
          Can&apos;t find the skill you need? Send a GitHub repo with a SKILL.md.
        </span>
      </div>
      <Dialog.Portal>
        <Dialog.Overlay className="skills-request-overlay" />
        <Dialog.Content className="skills-request-dialog">
          <div className="skills-request-dialog-header">
            <Dialog.Title>Request a Skill</Dialog.Title>
            <Dialog.Close asChild>
              <button className="skills-request-close" aria-label="Close" type="button">
                <X aria-hidden="true" size={18} />
              </button>
            </Dialog.Close>
          </div>
          <Dialog.Description className="skills-request-description">
            After a quick automated review, any valid skill files will be added to the
            marketplace.
          </Dialog.Description>
          <form className="skills-request-form" onSubmit={submitRequest}>
            <label htmlFor={inputId}>
              <span>
                <GitBranch aria-hidden="true" size={19} />
                GitHub repository URL
              </span>
              <input
                autoComplete="url"
                disabled={submitting}
                id={inputId}
                onChange={(event) => {
                  setRepositoryUrl(event.currentTarget.value);
                  setError("");
                  setSuccess("");
                }}
                placeholder="https://github.com/owner/repository/tree/main/skills/example"
                required
                type="url"
                value={repositoryUrl}
              />
            </label>
            {error ? <p className="skills-request-error">{error}</p> : null}
            {success ? <p className="skills-request-success">{success}</p> : null}
            <button
              className="skills-request-submit"
              disabled={submitting || !trimmedRepositoryUrl}
              type="submit"
            >
              {submitting ? <Loader2 aria-hidden="true" size={16} /> : null}
              <span>{submitting ? "Checking for SKILL.md..." : "Submit"}</span>
            </button>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function SkillsClient({
  auditEnabled,
  initialError,
  initialAuditStatus,
  initialOfficial,
  initialPagination,
  initialQuery,
  initialSearchCursor,
  initialSkills,
  initialView,
}: {
  auditEnabled: boolean;
  initialError: string;
  initialAuditStatus?: SkillAuditFilter;
  initialOfficial?: boolean;
  initialPagination: SkillPagination;
  initialQuery: string;
  initialSearchCursor: string;
  initialSkills: SkillRead[];
  initialView: SkillView;
}) {
  const searchInputId = useId();
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const didMountRef = useRef(false);
  const latestRequestId = useRef(0);
  const initialSearchQuery = initialQuery.trim();
  const [query, setQuery] = useState(initialSearchQuery);
  const [auditStatus, setAuditStatus] = useState<SkillAuditFilter | "">(
    auditEnabled ? (initialAuditStatus ?? "") : "",
  );
  const [official, setOfficial] = useState<SkillOfficialFilter>(
    initialOfficial === undefined ? "" : String(initialOfficial) as SkillOfficialFilter,
  );
  const [skills, setSkills] = useState<SkillRead[]>(initialSkills);
  const [pagination, setPagination] = useState<SkillPagination>(initialPagination);
  const [searchCursor, setSearchCursor] = useState(initialSearchCursor);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(initialError);
  const trimmedQuery = query.trim();
  const hasSearchQuery = trimmedQuery.length > 0;
  const canSearch = trimmedQuery.length >= 3;
  const hasMore = canSearch ? Boolean(searchCursor) : !hasSearchQuery && pagination.hasMore;
  const resultSummaryTitle = sourceFilterLabel(official);
  const resultSummaryDetail = hasSearchQuery
    ? canSearch
      ? `${skills.length.toLocaleString("en-US")}${searchCursor ? "+" : ""} ${
          skills.length === 1 && !searchCursor ? "result" : "results"
        }`
      : "Enter at least 3 characters to search"
    : `${pagination.total.toLocaleString("en-US")} ${
        pagination.total === 1 ? "result" : "results"
      }`;

  const reloadFirstPage = useCallback(async () => {
    const requestId = latestRequestId.current + 1;
    latestRequestId.current = requestId;
    setError("");
    setLoading(true);
    try {
      if (hasSearchQuery) {
        if (!canSearch) {
          setSkills([]);
          setSearchCursor("");
          return;
        }
        const response = await searchPublicSkillsPage({
          auditStatus: auditEnabled ? auditStatus || undefined : undefined,
          limit: SKILLS_PAGE_SIZE,
          official: official ? official === "true" : undefined,
          query: trimmedQuery,
        });
        if (latestRequestId.current !== requestId) return;
        setSkills(response.skills);
        setSearchCursor(response.nextCursor);
        return;
      }
      const response = await listPublicSkillsPage({
        auditStatus: auditEnabled ? auditStatus || undefined : undefined,
        limit: SKILLS_PAGE_SIZE,
        official: official ? official === "true" : undefined,
        query: hasSearchQuery ? trimmedQuery : undefined,
        view: initialView,
      });
      if (latestRequestId.current !== requestId) return;
      setSkills(response.skills);
      setPagination(response.pagination);
      setSearchCursor("");
    } catch (caught) {
      if (latestRequestId.current !== requestId) return;
      setError(caught instanceof Error ? caught.message : "Unable to load skills.");
      setSkills([]);
      setSearchCursor("");
    } finally {
      if (latestRequestId.current === requestId) setLoading(false);
    }
  }, [
    auditEnabled,
    auditStatus,
    canSearch,
    hasSearchQuery,
    initialView,
    official,
    trimmedQuery,
  ]);

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
    if (auditEnabled && auditStatus) {
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
  }, [auditEnabled, auditStatus, hasSearchQuery, official, trimmedQuery]);

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
          if (hasSearchQuery) {
            if (!canSearch) {
              setSkills([]);
              setSearchCursor("");
              return;
            }
            const response = await searchPublicSkillsPage({
              auditStatus: auditEnabled ? auditStatus || undefined : undefined,
              limit: SKILLS_PAGE_SIZE,
              official: official ? official === "true" : undefined,
              query: trimmedQuery,
            });
            if (latestRequestId.current !== requestId) return;
            setSkills(response.skills);
            setSearchCursor(response.nextCursor);
            return;
          }
          const response = await listPublicSkillsPage({
            auditStatus: auditEnabled ? auditStatus || undefined : undefined,
            limit: SKILLS_PAGE_SIZE,
            official: official ? official === "true" : undefined,
            query: hasSearchQuery ? trimmedQuery : undefined,
            view: initialView,
          });
          if (latestRequestId.current !== requestId) return;
          setSkills(response.skills);
          setPagination(response.pagination);
          setSearchCursor("");
        } catch (caught) {
          if (latestRequestId.current !== requestId) return;
          setError(caught instanceof Error ? caught.message : "Unable to load skills.");
          setSkills([]);
          setPagination(EMPTY_SKILLS_PAGINATION);
          setSearchCursor("");
        } finally {
          if (latestRequestId.current === requestId) setLoading(false);
        }
      })();
    }, SEARCH_DEBOUNCE_MS);

    return () => window.clearTimeout(timeoutId);
  }, [
    auditEnabled,
    auditStatus,
    canSearch,
    hasSearchQuery,
    initialView,
    official,
    trimmedQuery,
  ]);

  const loadMore = useCallback(async () => {
    if (!hasMore || loading) return;

    const requestId = latestRequestId.current + 1;
    latestRequestId.current = requestId;
    setLoading(true);
    setError("");
    try {
      if (canSearch) {
        if (!searchCursor) return;
        const response = await searchPublicSkillsPage({
          auditStatus: auditEnabled ? auditStatus || undefined : undefined,
          cursor: searchCursor,
          limit: SKILLS_PAGE_SIZE,
          official: official ? official === "true" : undefined,
          query: trimmedQuery,
        });
        if (latestRequestId.current !== requestId) return;
        setSkills((current) => [...current, ...response.skills]);
        setSearchCursor(response.nextCursor);
        return;
      }
      const response = await listPublicSkillsPage({
        auditStatus: auditEnabled ? auditStatus || undefined : undefined,
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
    auditEnabled,
    auditStatus,
    canSearch,
    hasMore,
    hasSearchQuery,
    initialView,
    loading,
    official,
    pagination.page,
    searchCursor,
    trimmedQuery,
  ]);

  return (
    <>
      <section className="registry-hero-section" aria-labelledby="skills-title">
        <div className="registry-hero-inner">
          <div className="registry-hero-copy">
            <h1 id="skills-title">Skills</h1>
            <p>
              Browse reusable agent skills, inspect published files, and follow trusted sources.
            </p>
            <div className="skills-hero-search-row">
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
              <RequestSkillDialog onImported={reloadFirstPage} />
            </div>
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
            {auditEnabled ? (
              <SkillsFilterGroup<SkillAuditFilter | "">
                label="Audit"
                onChange={updateAuditStatus}
                options={SKILL_AUDIT_FILTER_OPTIONS}
                value={auditStatus}
              />
            ) : null}
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
                        ...(auditEnabled && auditStatus ? { audit_status: auditStatus } : {}),
                        ...(official ? { official } : {}),
                        ...(hasSearchQuery ? { q: trimmedQuery } : {}),
                      },
                    }}
                    key={value}
                    prefetch={false}
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
                <SkillLeaderboard auditEnabled={auditEnabled} skills={skills} />
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
