"use client";

import Link from "next/link";
import {
  AlertCircle,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  CircleDashed,
  Clock3,
  FileCheck2,
  FileText,
  GitBranch,
  Pencil,
  Plus,
  RefreshCw,
  SearchX,
  Sparkles,
  Trash2,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { AiSubmissionPromptDialog } from "@/components/ai-submission-prompt-dialog";
import { PublicHeader } from "@/components/site-header";
import { ServerIcon } from "@/components/server-icon";
import { Button } from "@/components/ui/button";
import { HubApiError, currentUser, deleteSubmission, listSubmissions } from "@/lib/api/hub";
import type { SubmissionRead } from "@/lib/api/generated/model";
import { cn } from "@/lib/utils";

type LoadState = "loading" | "ready" | "error" | "auth";
type StatusFilter = "all" | SubmissionRead["status"];
type SubmissionGroup = {
  latest: SubmissionRead;
  name: string;
  submissions: SubmissionRead[];
};

const statusOrder: SubmissionRead["status"][] = [
  "draft",
  "submitted",
  "approved",
  "rejected",
  "withdrawn",
  "published",
];

const statusMeta: Record<
  SubmissionRead["status"],
  {
    badge: string;
    icon: typeof CircleDashed;
    label: string;
  }
> = {
  approved: {
    badge: "border-emerald-200 bg-emerald-50 text-emerald-700",
    icon: CheckCircle2,
    label: "Approved",
  },
  draft: {
    badge: "border-slate-200 bg-slate-50 text-slate-700",
    icon: CircleDashed,
    label: "Draft",
  },
  published: {
    badge: "border-green-200 bg-green-50 text-green-700",
    icon: CheckCircle2,
    label: "Published",
  },
  rejected: {
    badge: "border-red-200 bg-red-50 text-red-700",
    icon: XCircle,
    label: "Rejected",
  },
  submitted: {
    badge: "border-amber-200 bg-amber-50 text-amber-700",
    icon: Clock3,
    label: "In review",
  },
  withdrawn: {
    badge: "border-zinc-200 bg-zinc-50 text-zinc-700",
    icon: XCircle,
    label: "Withdrawn",
  },
};

const submissionTypeLabels: Record<SubmissionRead["submissionType"], string> = {
  metadata_edit: "Metadata edit",
  new_server: "New server",
  new_version: "New version",
  takedown_appeal: "Appeal",
};

function formatDate(value?: string | null) {
  if (!value) return "Not set";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function isEditableSubmission(status: SubmissionRead["status"]) {
  return status !== "published";
}

function isDeleteableSubmission(status: SubmissionRead["status"]) {
  return status !== "published";
}

function getStatusCounts(submissions: SubmissionRead[]) {
  return submissions.reduce(
    (counts, submission) => {
      counts[submission.status] += 1;
      counts.all += 1;
      return counts;
    },
    {
      all: 0,
      approved: 0,
      draft: 0,
      published: 0,
      rejected: 0,
      submitted: 0,
      withdrawn: 0,
    } satisfies Record<StatusFilter, number>,
  );
}

function sortSubmissions(submissions: SubmissionRead[]) {
  return [...submissions].sort((left, right) => {
    return new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime();
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function submissionIconUrl(submission: SubmissionRead) {
  const icons = isRecord(submission.serverJson) ? submission.serverJson.icons : null;
  if (!Array.isArray(icons)) return "";
  const icon = icons.find((item) => {
    if (!isRecord(item)) return false;
    return typeof item.src === "string" || typeof item.url === "string";
  });
  if (!isRecord(icon)) return "";
  return typeof icon.src === "string" ? icon.src : typeof icon.url === "string" ? icon.url : "";
}

function groupSubmissionsByServer(submissions: SubmissionRead[]) {
  const groups = new Map<string, SubmissionRead[]>();

  for (const submission of submissions) {
    groups.set(submission.name, [...(groups.get(submission.name) ?? []), submission]);
  }

  return [...groups.entries()]
    .map(([name, groupedSubmissions]) => {
      const sorted = sortSubmissions(groupedSubmissions);
      return {
        latest: sorted[0],
        name,
        submissions: sorted,
      };
    })
    .filter((group): group is SubmissionGroup => Boolean(group.latest))
    .sort((left, right) => {
      return new Date(right.latest.updatedAt).getTime() - new Date(left.latest.updatedAt).getTime();
    });
}

function StatePanel({
  action,
  detail,
  icon: Icon,
  tone = "default",
  title,
}: {
  action?: React.ReactNode;
  detail: string;
  icon: typeof FileCheck2;
  tone?: "default" | "danger";
  title: string;
}) {
  return (
    <div
      className={cn(
        "grid min-h-80 place-items-center rounded-lg border border-dashed bg-white px-6 py-12 text-center shadow-[var(--shadow-card)]",
        tone === "danger" ? "border-red-200 bg-red-50/40" : "border-border",
      )}
    >
      <div className="grid max-w-md justify-items-center gap-4">
        <span
          className={cn(
            "inline-flex size-12 items-center justify-center rounded-full border",
            tone === "danger"
              ? "border-red-200 bg-white text-red-600"
              : "border-slate-200 bg-slate-50 text-slate-600",
          )}
        >
          <Icon className="size-5" />
        </span>
        <div className="grid gap-1">
          <h2 className="text-lg font-semibold text-foreground">{title}</h2>
          <p className="text-sm leading-6 text-muted-foreground">{detail}</p>
        </div>
        {action}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: SubmissionRead["status"] }) {
  const meta = statusMeta[status];
  const Icon = meta.icon;

  return (
    <span
      className={cn(
        "inline-flex min-h-7 items-center gap-1.5 rounded-full border px-3 text-xs font-bold",
        meta.badge,
      )}
    >
      <Icon className="size-3.5" />
      {meta.label}
    </span>
  );
}

function AddSubmissionMenu() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [promptOpen, setPromptOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;

    function closeOnOutsideClick(event: MouseEvent) {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }

    window.addEventListener("mousedown", closeOnOutsideClick);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("mousedown", closeOnOutsideClick);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [menuOpen]);

  return (
    <>
      <div className="relative" ref={menuRef}>
        <div className="inline-flex rounded-[var(--radius)] shadow-[var(--shadow-card)]">
          <Button asChild className="rounded-r-none shadow-none">
            <Link href="/submit">
              <Plus className="size-4" />
              Add submission
            </Link>
          </Button>
          <Button
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            aria-label="More submission options"
            className="rounded-l-none border-l border-white/20 px-2 shadow-none"
            onClick={() => setMenuOpen((current) => !current)}
            type="button"
          >
            <ChevronDown className="size-4" />
          </Button>
        </div>
        {menuOpen ? (
          <div
            className="absolute right-0 top-11 z-20 grid w-56 overflow-hidden rounded-lg border border-border bg-white p-1 shadow-xl"
            role="menu"
          >
            <button
              className="flex items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm font-semibold text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => {
                setMenuOpen(false);
                setPromptOpen(true);
              }}
              role="menuitem"
              type="button"
            >
              <Sparkles className="size-4 text-muted-foreground" />
              AI prompt
            </button>
          </div>
        ) : null}
      </div>
      <AiSubmissionPromptDialog onOpenChange={setPromptOpen} open={promptOpen} />
    </>
  );
}

function VersionSubmissionRow({
  deleting,
  onDelete,
  submission,
}: {
  deleting: boolean;
  onDelete: (submission: SubmissionRead) => void;
  submission: SubmissionRead;
}) {
  const isEditable = isEditableSubmission(submission.status);
  const isDeleteable = isDeleteableSubmission(submission.status);
  const typeLabel = submissionTypeLabels[submission.submissionType] ?? submission.submissionType;
  const Icon = submission.submissionType === "new_version" ? GitBranch : FileText;

  return (
    <div className="grid gap-3 rounded-md border border-slate-100 bg-slate-50/70 p-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
      <div className="grid min-w-0 gap-3 sm:grid-cols-[36px_minmax(0,1fr)]">
        <Link
          aria-label={`Open ${submission.name} ${submission.version}`}
          className="inline-flex size-9 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-700 transition-colors hover:border-slate-300 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300"
          href={`/submissions/${submission.id}`}
        >
          <Icon className="size-4" />
        </Link>
        <div className="grid min-w-0 gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Link
              className="font-bold text-foreground hover:underline"
              href={`/submissions/${submission.id}`}
            >
              v{submission.version}
            </Link>
            <StatusBadge status={submission.status} />
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <span>{typeLabel}</span>
            <span aria-hidden="true">/</span>
            <span>Updated {formatDate(submission.updatedAt)}</span>
            {submission.submittedAt ? (
              <>
                <span aria-hidden="true">/</span>
                <span>Submitted {formatDate(submission.submittedAt)}</span>
              </>
            ) : null}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 lg:justify-end">
        <Button asChild size="sm">
          <Link
            href={
              isEditable
                ? `/submit?submission=${submission.id}`
                : `/submit?submission=${submission.id}&version=new`
            }
          >
            {isEditable ? <Pencil className="size-4" /> : <Plus className="size-4" />}
            {isEditable ? "Edit" : "New version"}
          </Link>
        </Button>
        {isDeleteable ? (
          <Button
            aria-label={`Delete ${submission.name} ${submission.version}`}
            disabled={deleting}
            onClick={() => onDelete(submission)}
            size="sm"
            type="button"
            variant="destructive"
          >
            <Trash2 className="size-4" />
            {deleting ? "Deleting" : "Delete"}
          </Button>
        ) : null}
      </div>

      {submission.rejectionMessage ? (
        <div className="rounded-md border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700 lg:col-span-2">
          {submission.rejectionMessage}
        </div>
      ) : null}
    </div>
  );
}

function SubmissionGroupCard({
  deletingId,
  group,
  onDelete,
}: {
  deletingId: string;
  group: SubmissionGroup;
  onDelete: (submission: SubmissionRead) => void;
}) {
  const versionCount = group.submissions.length;
  const iconUrl =
    submissionIconUrl(group.latest) ||
    group.submissions.map(submissionIconUrl).find(Boolean) ||
    "";

  return (
    <article className="grid gap-4 rounded-lg border border-border bg-white p-4 shadow-[var(--shadow-card)] transition-shadow hover:shadow-[0_8px_24px_rgb(15_23_42_/_7%)]">
      <div className="grid min-w-0 gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Link
            aria-label={`Open latest submission for ${group.name}`}
            className="inline-flex focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300"
            href={`/submissions/${group.latest.id}`}
          >
            <ServerIcon src={iconUrl} title={group.name} />
          </Link>
          <Link
            className="min-w-0 overflow-hidden text-ellipsis text-base font-bold text-foreground hover:underline"
            href={`/submissions/${group.latest.id}`}
          >
            {group.name}
          </Link>
          <StatusBadge status={group.latest.status} />
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <span className="font-semibold text-foreground">
            {versionCount} {versionCount === 1 ? "submission" : "submissions"}
          </span>
          <span aria-hidden="true">/</span>
          <span>Latest v{group.latest.version}</span>
          <span aria-hidden="true">/</span>
          <span>Updated {formatDate(group.latest.updatedAt)}</span>
        </div>
      </div>

      <div className="grid gap-2">
        {group.submissions.map((submission) => (
          <VersionSubmissionRow
            deleting={deletingId === submission.id}
            key={submission.id}
            onDelete={onDelete}
            submission={submission}
          />
        ))}
      </div>
    </article>
  );
}

export default function SubmissionsPage() {
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [deletingId, setDeletingId] = useState("");
  const [submissions, setSubmissions] = useState<SubmissionRead[]>([]);
  const [filter, setFilter] = useState<StatusFilter>("all");

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setState("loading");
      setError("");
      Promise.all([currentUser(), listSubmissions()])
        .then(([current, response]) => {
          setSubmissions(
            sortSubmissions(
              response.submissions.filter(
                (submission) => submission.submitterUserId === current.id,
              ),
            ),
          );
          setState("ready");
        })
        .catch((caught) => {
          setError(caught instanceof Error ? caught.message : "Unable to load submissions.");
          setState(caught instanceof HubApiError && caught.status === 401 ? "auth" : "error");
        });
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, []);

  const counts = useMemo(() => getStatusCounts(submissions), [submissions]);
  const filteredSubmissions = useMemo(() => {
    if (filter === "all") return submissions;
    return submissions.filter((submission) => submission.status === filter);
  }, [filter, submissions]);
  const allGroupedSubmissions = useMemo(() => groupSubmissionsByServer(submissions), [submissions]);
  const groupedSubmissions = useMemo(
    () => groupSubmissionsByServer(filteredSubmissions),
    [filteredSubmissions],
  );
  const visibleStatusFilters = useMemo(() => {
    return statusOrder.filter((status) => counts[status] > 0 || filter === status);
  }, [counts, filter]);

  async function handleDeleteSubmission(submission: SubmissionRead) {
    if (!isDeleteableSubmission(submission.status)) return;
    const confirmed = window.confirm(
      `Delete submission ${submission.name} v${submission.version}? This cannot be undone.`,
    );
    if (!confirmed) return;

    setDeletingId(submission.id);
    setActionError("");
    try {
      await deleteSubmission(submission.id);
      setSubmissions((current) => current.filter((item) => item.id !== submission.id));
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "Unable to delete submission.");
    } finally {
      setDeletingId("");
    }
  }

  return (
    <>
      <PublicHeader />
      <main
        className="min-h-[calc(100dvh-64px)] bg-[#f6f8fb] py-8"
        style={{
          paddingInline:
            "max(var(--content-gutter), calc((100vw - var(--content-max-width)) / 2 + var(--content-gutter)))",
        }}
      >
        <div className="grid gap-5">
          <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div className="grid gap-1">
              <h1 className="flex items-center gap-2 text-3xl font-black tracking-normal text-foreground">
                <FileCheck2 className="size-6 text-muted-foreground" />
                <span>
                  Submission review
                </span>
              </h1>
              <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                Track MCP server drafts, reviews, and published versions.
              </p>
            </div>
            <AddSubmissionMenu />
          </header>

          <section className="grid gap-4">
            {actionError ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {actionError}
              </div>
            ) : null}
            <div className="flex flex-col gap-3 rounded-lg border border-border bg-white px-3 py-3 shadow-[var(--shadow-card)] lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="mr-1 text-sm font-bold text-foreground">
                  {allGroupedSubmissions.length}{" "}
                  {allGroupedSubmissions.length === 1 ? "server" : "servers"}
                  <span className="ml-1 text-muted-foreground">
                    / {counts.all} {counts.all === 1 ? "submission" : "submissions"}
                  </span>
                </span>
                <button
                  className={cn(
                    "inline-flex min-h-9 items-center gap-2 rounded-md border px-3 text-sm font-bold",
                    filter === "all"
                      ? "border-slate-900 bg-slate-900 text-white"
                      : "border-border bg-white text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                  onClick={() => setFilter("all")}
                  type="button"
                >
                  All
                  <span className="rounded bg-white/15 px-1.5 text-xs">{counts.all}</span>
                </button>
                {visibleStatusFilters.map((status) => (
                  <button
                    className={cn(
                      "inline-flex min-h-9 items-center gap-2 rounded-md border px-3 text-sm font-bold",
                      filter === status
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-border bg-white text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                    key={status}
                    onClick={() => setFilter(status)}
                    type="button"
                  >
                    {statusMeta[status].label}
                    <span className="rounded bg-current/10 px-1.5 text-xs">{counts[status]}</span>
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <CalendarClock className="size-4" />
                Sorted by latest update
              </div>
            </div>

            {state === "loading" ? (
              <StatePanel
                detail="Fetching the latest submission records for your account."
                icon={RefreshCw}
                title="Loading submissions"
              />
            ) : null}
            {state === "auth" ? (
              <StatePanel
                action={
                  <Button asChild size="sm">
                    <Link href="/login?next=submissions">Sign in</Link>
                  </Button>
                }
                detail="Authentication is required before submission records can be shown."
                icon={FileCheck2}
                title="Sign in required"
              />
            ) : null}
            {state === "error" ? (
              <StatePanel detail={error} icon={AlertCircle} title="Unable to load submissions" tone="danger" />
            ) : null}
            {state === "ready" && submissions.length === 0 ? (
              <StatePanel
                action={<AddSubmissionMenu />}
                detail="Create the first registry submission for a server or version."
                icon={FileCheck2}
                title="No submissions yet"
              />
            ) : null}
            {state === "ready" && submissions.length > 0 && filteredSubmissions.length === 0 ? (
              <StatePanel
                detail="No submissions match the selected status."
                icon={SearchX}
                title="Nothing in this status"
              />
            ) : null}
            {state === "ready" && groupedSubmissions.length > 0 ? (
              <div className="grid gap-3">
                {groupedSubmissions.map((group) => (
                  <SubmissionGroupCard
                    deletingId={deletingId}
                    group={group}
                    key={group.name}
                    onDelete={handleDeleteSubmission}
                  />
                ))}
              </div>
            ) : null}
          </section>
        </div>
      </main>
    </>
  );
}
