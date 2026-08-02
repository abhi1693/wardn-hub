"use client";

import * as Dialog from "@radix-ui/react-dialog";
import {
  BadgeCheck,
  GitBranch,
  Globe2,
  ListFilter,
  Loader2,
  PackagePlus,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  Tags,
  UsersRound,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { InfiniteScrollTrigger } from "@/components/infinite-scroll-trigger";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "@/components/ui/select";
import type {
  RegistryCategoryRead,
  SkillPagination,
  SkillRead,
} from "@/lib/api/generated/model";
import { SKILLS_PAGE_SIZE } from "@/lib/public-listing-limits";
import {
  importPublicGitHubSkill,
  listPublicSkillsPage,
  searchPublicSkillsPage,
} from "@/lib/public-skills";
import { SkillCardGrid } from "./skills-ui";

const SEARCH_DEBOUNCE_MS = 250;
const CATEGORY_ALL_SELECT_VALUE = "__all_categories__";
const UNCATEGORIZED_CATEGORY_VALUE = "uncategorized";
type SkillAuditFilter = "fail" | "pass" | "warn";
type SkillView = "all-time" | "hot" | "latest" | "oldest" | "trending";
const SKILL_VIEW_PATHS: Record<SkillView, string> = {
  "all-time": "/skills",
  hot: "/skills/hot",
  latest: "/skills/latest",
  oldest: "/skills/oldest",
  trending: "/skills/trending",
};
const SKILL_VIEW_OPTIONS: Array<{ label: string; value: SkillView }> = [
  { label: "All time", value: "all-time" },
  { label: "Latest", value: "latest" },
  { label: "Oldest", value: "oldest" },
  { label: "Trending 7d", value: "trending" },
  { label: "Hot 24h", value: "hot" },
];
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

function officialFilterValue(value?: boolean): SkillOfficialFilter {
  if (value === undefined) return "";
  return value ? "true" : "false";
}

function categoryFilterLabel(value: string, categories: RegistryCategoryRead[]) {
  if (!value) return "";
  if (value === UNCATEGORIZED_CATEGORY_VALUE) return "Uncategorized";
  return categories.find((category) => category.slug === value)?.name ?? value;
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

function SkillsFilterSelect<T extends string>({
  ariaLabel,
  icon: Icon,
  label,
  onChange,
  options,
  value,
}: {
  ariaLabel: string;
  icon: LucideIcon;
  label: string;
  onChange: (value: T) => void;
  options: Array<{ label: string; value: T }>;
  value: T;
}) {
  const selectedLabel = options.find((option) => option.value === value)?.label ?? "";

  return (
    <div className="skills-filter-group">
      <h2>{label}</h2>
      <Select onValueChange={(nextValue) => onChange(nextValue as T)} value={value}>
        <SelectTrigger aria-label={ariaLabel} className="skills-filter-select-trigger">
          <span className="skills-filter-select-content">
            <Icon aria-hidden="true" size={14} />
            <span>{selectedLabel}</span>
          </span>
        </SelectTrigger>
        <SelectContent className="skills-filter-select-content-menu">
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
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

const SKILLS_SCORECARD_ROWS = [
  {
    label: "Job",
    value: "The skill names the repeatable work, not only a persona.",
  },
  {
    label: "Scope",
    value: "Inputs, outputs, and boundaries are clear before you apply it.",
  },
  {
    label: "Evidence",
    value: "Source, snapshot, files, and audit result all point to the same use case.",
  },
  {
    label: "Fit",
    value: "It improves one workflow you already run, not every task in your backlog.",
  },
];

const SKILLS_REVIEW_FLOW = [
  {
    phase: "Search",
    title: "Start with the outcome",
    copy:
      "Use the job you want done: debugging, writing, browser automation, Kubernetes review, research synthesis, or another concrete workflow.",
    output: "A short list of skills with matching names and descriptions.",
  },
  {
    phase: "Compare",
    title: "Check the package behind the promise",
    copy:
      "Open the detail page and read the source, bundled files, snapshot metadata, categories, and audit status before trusting the summary.",
    output: "One candidate that matches the actual files, not just the pitch.",
  },
  {
    phase: "Adopt",
    title: "Use the narrowest useful skill",
    copy:
      "Prefer a skill that handles one repeatable workflow well. Broad assistants are harder to review, test, and replace.",
    output: "A reusable workflow you can explain to another operator.",
  },
  {
    phase: "Revisit",
    title: "Treat updates like dependency changes",
    copy:
      "When a skill changes source, snapshot, audit status, or category, inspect it again before letting it shape production work.",
    output: "A maintained skill set that stays understandable over time.",
  },
];

const SKILLS_TRUST_ROWS = [
  {
    signal: "Source",
    strong: "Repository, owner, and bundled files are visible.",
    weak: "The source is vague, forked without context, or hard to inspect.",
  },
  {
    signal: "Category",
    strong: "The category describes the primary workflow outcome.",
    weak: "Several unrelated categories are mixed together, or no category fits.",
  },
  {
    signal: "Audit",
    strong: "Pass, warning, or failure is easy to interpret from the skill page.",
    weak: "A warning is ignored, or a failed audit is treated like a popularity issue.",
  },
  {
    signal: "Description",
    strong: "The copy explains when to use the skill and what it produces.",
    weak: "It promises expertise without naming inputs, outputs, or limits.",
  },
];

const SKILLS_FAQS = [
  {
    question: "What is an agent skill?",
    answer:
      "An agent skill is a packaged set of instructions and supporting files that helps an AI agent perform a specific kind of work more consistently, such as debugging, writing, research, or operating a domain-specific workflow.",
  },
  {
    question: "How should I compare two similar skills?",
    answer:
      "Compare the stated outcome, source repository, install count, categories, and audit result. The better fit is usually the skill with the narrower workflow and clearer maintenance trail, not simply the one with the broadest description.",
  },
  {
    question: "What do official and community sources mean?",
    answer:
      "Official sources identify publishers that Wardn Hub marks as trusted or canonical for that catalog entry. Community sources can still be useful, but they deserve closer inspection before use in production agent workflows.",
  },
  {
    question: "Why do some skills have warnings or no category?",
    answer:
      "A warning means the automated audit found something worth reviewing. A missing category usually means the primary use case is ambiguous or the taxonomy does not yet have a defensible bucket for that skill.",
  },
];

function categorySkillDescription(category: RegistryCategoryRead) {
  const description = category.description?.trim();
  if (!description) {
    return `Skills for ${category.name.toLowerCase()} workflows and related operating tasks.`;
  }
  return description
    .replace(/\bMCP servers\b/g, "agent workflows")
    .replace(/\bMCP server\b/g, "agent workflow");
}

function SkillsLibraryGuide({ categories }: { categories: RegistryCategoryRead[] }) {
  const guideCategories = categories.slice(0, 12);

  return (
    <section className="skills-guide-content" aria-label="Agent skills guide">
      <section className="skills-guide-opener" aria-labelledby="skills-guide-title">
        <div className="skills-guide-opener-copy">
          <span>Skill selection field guide</span>
          <h2 id="skills-guide-title">Pick skills by the work they make repeatable.</h2>
          <p>
            The right skill is closer to a dependency than a prompt snippet. It should have a
            specific job, inspectable source, a current snapshot, and enough audit context to decide
            whether it belongs in your agent setup.
          </p>
        </div>
        <div className="skills-guide-scorecard" aria-label="Skill fit scorecard">
          <div className="skills-guide-scorecard-head">
            <span>Before install</span>
            <strong>Fit check</strong>
          </div>
          {SKILLS_SCORECARD_ROWS.map((item) => (
            <div className="skills-guide-scorecard-row" key={item.label}>
              <span>{item.label}</span>
              <p>{item.value}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="skills-playbook-section" aria-labelledby="skills-playbook-title">
        <div className="skills-guide-section-heading">
          <span>Review workflow</span>
          <h2 id="skills-playbook-title">Evaluate a skill before it shapes an agent response</h2>
          <p>
            Popularity can help you discover candidates, but it should not decide adoption. Use a
            repeatable review path so every skill is judged by the same signals.
          </p>
        </div>
        <ol className="skills-playbook-flow" aria-label="Skill review workflow">
          {SKILLS_REVIEW_FLOW.map((item, index) => (
            <li key={item.phase}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div>
                <small>{item.phase}</small>
                <h3>{item.title}</h3>
                <p>{item.copy}</p>
              </div>
              <strong>{item.output}</strong>
            </li>
          ))}
        </ol>
      </section>

      <section className="skills-trust-section" aria-labelledby="skills-trust-title">
        <div className="skills-guide-section-heading">
          <span>Trust signals</span>
          <h2 id="skills-trust-title">Separate useful workflow packages from prompt dumps</h2>
        </div>
        <div className="skills-trust-matrix" role="table" aria-label="Skill trust signals">
          <div className="skills-trust-row header" role="row">
            <span role="columnheader">Signal</span>
            <span role="columnheader">Looks strong</span>
            <span role="columnheader">Needs caution</span>
          </div>
          {SKILLS_TRUST_ROWS.map((item) => (
            <div className="skills-trust-row" role="row" key={item.signal}>
              <strong role="cell">{item.signal}</strong>
              <p role="cell">{item.strong}</p>
              <p role="cell">{item.weak}</p>
            </div>
          ))}
        </div>
      </section>

      {guideCategories.length ? (
        <section className="skills-category-guide" aria-labelledby="skills-category-guide-title">
          <div className="skills-guide-section-heading">
            <span>Category field guide</span>
            <h2 id="skills-category-guide-title">Browse the top 12 skill categories</h2>
            <p>
              Categories should help you start with intent. Search by the kind of work you need
              done, then use the skill detail page to confirm that the bundle really supports it.
            </p>
          </div>
          <div className="skills-category-guide-list">
            {guideCategories.map((item, index) => (
              <Link
                className="skills-category-guide-card"
                href={`/skills?category=${encodeURIComponent(item.slug)}`}
                key={item.slug}
              >
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <h3>{item.name}</h3>
                  <p>{categorySkillDescription(item)}</p>
                </div>
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      <section className="skills-faq-section" aria-labelledby="skills-faq-title">
        <div className="skills-guide-section-heading">
          <span>Skill review basics</span>
          <h2 id="skills-faq-title">Questions to answer before adopting a skill</h2>
        </div>
        <div className="skills-faq-list">
          {SKILLS_FAQS.map((item) => (
            <details className="skills-faq-item" key={item.question}>
              <summary>{item.question}</summary>
              <p>{item.answer}</p>
            </details>
          ))}
        </div>
      </section>
    </section>
  );
}

export function SkillsClient({
  auditEnabled,
  initialError,
  initialAuditStatus,
  initialCategories,
  initialCategory,
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
  initialCategories: RegistryCategoryRead[];
  initialCategory: string;
  initialOfficial?: boolean;
  initialPagination: SkillPagination;
  initialQuery: string;
  initialSearchCursor: string;
  initialSkills: SkillRead[];
  initialView: SkillView;
}) {
  const router = useRouter();
  const searchInputId = useId();
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const didMountRef = useRef(false);
  const latestRequestId = useRef(0);
  const initialSearchQuery = initialQuery.trim();
  const [query, setQuery] = useState(initialSearchQuery);
  const [auditStatus, setAuditStatus] = useState<SkillAuditFilter | "">(
    auditEnabled ? (initialAuditStatus ?? "") : "",
  );
  const [category, setCategory] = useState(initialCategory);
  const [official, setOfficial] = useState<SkillOfficialFilter>(
    officialFilterValue(initialOfficial),
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
  const resultSummaryTitle = category
    ? categoryFilterLabel(category, initialCategories)
    : sourceFilterLabel(official);
  const resultSummaryDetail = hasSearchQuery
    ? canSearch
      ? `${skills.length.toLocaleString("en-US")}${searchCursor ? "+" : ""} ${
          skills.length === 1 && !searchCursor ? "result" : "results"
        }`
      : "Enter at least 3 characters to search"
    : `${pagination.total.toLocaleString("en-US")} ${
        pagination.total === 1 ? "result" : "results"
      }`;
  const viewPath = useCallback(
    (view: SkillView) => {
      const params = new URLSearchParams();
      if (auditEnabled && auditStatus) params.set("audit_status", auditStatus);
      if (category) params.set("category", category);
      if (official) params.set("official", official);
      if (hasSearchQuery) params.set("q", trimmedQuery);
      const queryString = params.toString();
      return `${SKILL_VIEW_PATHS[view]}${queryString ? `?${queryString}` : ""}`;
    },
    [auditEnabled, auditStatus, category, hasSearchQuery, official, trimmedQuery],
  );
  const updateView = useCallback(
    (view: SkillView) => {
      if (view !== initialView) router.push(viewPath(view));
    },
    [initialView, router, viewPath],
  );

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
          category: category || undefined,
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
        category: category || undefined,
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
    category,
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

  const updateCategory = useCallback((nextCategory: string) => {
    latestRequestId.current += 1;
    setCategory(nextCategory);
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
    if (category) {
      url.searchParams.set("category", category);
    } else {
      url.searchParams.delete("category");
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
  }, [auditEnabled, auditStatus, category, hasSearchQuery, official, trimmedQuery]);

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
              category: category || undefined,
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
            category: category || undefined,
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
    category,
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
          category: category || undefined,
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
        category: category || undefined,
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
    category,
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
          <div className="skills-product-hero-grid">
            <div className="skills-product-hero-copy skills-hero-copy">
              <span className="registry-hero-eyebrow">Agent Skills Library</span>
              <h1 id="skills-title">Discover agent skills for real workflows</h1>
              <p>
                Search reusable agent workflows, compare source and audit signals, and inspect the
                bundle before it becomes part of your setup.
              </p>
            </div>
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
                    placeholder="Search debugging, writing, browser automation..."
                    ref={searchInputRef}
                    type="search"
                    value={query}
                  />
                </label>
              </form>
            </div>
            <p className="skills-hero-proofline">
              Browse by outcome, audit status, maintenance signal, and install activity.
            </p>
          </div>
        </div>
      </section>

      <section className="content-section skills-library-section" aria-label="Skills">
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
            <SkillsFilterSelect
              ariaLabel="Category"
              icon={Tags}
              label="Category"
              onChange={(nextCategory) =>
                updateCategory(
                  nextCategory === CATEGORY_ALL_SELECT_VALUE ? "" : nextCategory,
                )
              }
              options={[
                { label: "All categories", value: CATEGORY_ALL_SELECT_VALUE },
                { label: "Uncategorized", value: UNCATEGORIZED_CATEGORY_VALUE },
                ...initialCategories.map((item) => ({
                  label: item.name,
                  value: item.slug,
                })),
              ]}
              value={category || CATEGORY_ALL_SELECT_VALUE}
            />
            <SkillsFilterSelect
              ariaLabel="Skill leaderboard view"
              icon={ListFilter}
              label="View"
              onChange={(nextView) => updateView(nextView)}
              options={SKILL_VIEW_OPTIONS}
              value={initialView}
            />
          </aside>
          <div className="registry-results-shell">
            <div className="skills-results-toolbar">
              <div className="skills-results-heading">
                <h2>{resultSummaryTitle}</h2>
                <p aria-live="polite">{loading ? "Updating results…" : resultSummaryDetail}</p>
              </div>
              <RequestSkillDialog onImported={reloadFirstPage} />
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
                <SkillCardGrid auditEnabled={auditEnabled} skills={skills} variant="directory" />
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
        <SkillsLibraryGuide categories={initialCategories} />
      </section>
    </>
  );
}
