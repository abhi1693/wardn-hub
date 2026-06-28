"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  AlertCircle,
  Archive,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleDashed,
  Clock3,
  FileCheck2,
  FileText,
  GitBranch,
  Pencil,
  Plus,
  SearchX,
  Sparkles,
  Trash2,
  XCircle,
} from "lucide-react";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { AiDraftFixPromptDialog } from "@/components/ai-draft-fix-prompt-dialog";
import { AiSubmissionPromptDialog } from "@/components/ai-submission-prompt-dialog";
import { AiUrlDraftPromptDialog } from "@/components/ai-url-draft-prompt-dialog";
import { AiValidationPromptDialog } from "@/components/ai-validation-prompt-dialog";
import { ProtectedRouteState } from "@/components/protected-route-state";
import { PublicHeader } from "@/components/site-header";
import { ServerIcon } from "@/components/server-icon";
import { Button } from "@/components/ui/button";
import {
  HubApiError,
  archiveServer,
  currentUser,
  deleteSubmission,
  listSubmissions,
  rejectSubmission,
  submissionAction,
} from "@/lib/api/hub";
import type {
  SubmissionListMetadata,
  SubmissionRead,
  SubmissionStatusCounts,
  UserRead,
} from "@/lib/api/generated/model";
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
const SUBMISSIONS_PAGE_SIZE = 20;
const statusValues = new Set<StatusFilter>(["all", ...statusOrder]);
const emptyStatusCounts = {
  all: 0,
  approved: 0,
  draft: 0,
  published: 0,
  rejected: 0,
  submitted: 0,
  withdrawn: 0,
} satisfies Required<SubmissionStatusCounts>;

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

function canReviewSubmissions(user: UserRead | null) {
  return Boolean(user?.is_superuser || user?.is_global_moderator);
}

function canUseReviewActions(user: UserRead | null) {
  return Boolean(user?.is_superuser || user?.is_global_moderator);
}

function canPublishSubmissions(user: UserRead | null) {
  return Boolean(user?.is_superuser);
}

function statusFilterFromQuery(value: string | null): StatusFilter {
  if (!value) return "all";
  return statusValues.has(value as StatusFilter) ? (value as StatusFilter) : "all";
}

function pageFromQuery(value: string | null) {
  const page = Number.parseInt(value ?? "", 10);
  return Number.isFinite(page) && page > 0 ? page : 1;
}

function currentPathWithQuery(pathname: string, searchParams: { toString: () => string }) {
  const queryString = searchParams.toString();
  return queryString ? `${pathname}?${queryString}` : pathname;
}

function submitHref(params: Record<string, string>, returnTo: string) {
  const queryParams = new URLSearchParams(params);
  queryParams.set("returnTo", returnTo);
  return `/submit?${queryParams.toString()}`;
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
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const returnTo = currentPathWithQuery(pathname, searchParams);
  const [menuOpen, setMenuOpen] = useState(false);
  const [promptOpen, setPromptOpen] = useState(false);
  const [urlDraftPromptOpen, setUrlDraftPromptOpen] = useState(false);
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
            <Link href={submitHref({}, returnTo)}>
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
              Submit from GitHub repo
            </button>
            <button
              className="flex items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm font-semibold text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => {
                setMenuOpen(false);
                setUrlDraftPromptOpen(true);
              }}
              role="menuitem"
              type="button"
            >
              <FileText className="size-4 text-muted-foreground" />
              Draft from docs URL
            </button>
          </div>
        ) : null}
      </div>
      <AiSubmissionPromptDialog onOpenChange={setPromptOpen} open={promptOpen} />
      <AiUrlDraftPromptDialog
        onOpenChange={setUrlDraftPromptOpen}
        open={urlDraftPromptOpen}
      />
    </>
  );
}

function VersionSubmissionRow({
  canMutate,
  canPublish,
  canValidate,
  canReview,
  deleting,
  onDelete,
  onOpenFixPrompt,
  onOpenValidationPrompt,
  onReviewAction,
  reviewingActionId,
  submission,
}: {
  canMutate: boolean;
  canPublish: boolean;
  canValidate: boolean;
  canReview: boolean;
  deleting: boolean;
  onDelete: (submission: SubmissionRead) => void;
  onOpenFixPrompt: (submission: SubmissionRead) => void;
  onOpenValidationPrompt: (submission: SubmissionRead) => void;
  onReviewAction: (
    submission: SubmissionRead,
    action: "approve" | "approve_publish" | "reject" | "publish",
  ) => void;
  reviewingActionId: string;
  submission: SubmissionRead;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const returnTo = currentPathWithQuery(pathname, searchParams);
  const isEditable = isEditableSubmission(submission.status);
  const isDeleteable = isDeleteableSubmission(submission.status);
  const typeLabel = submissionTypeLabels[submission.submissionType] ?? submission.submissionType;
  const Icon = submission.submissionType === "new_version" ? GitBranch : FileText;
  const isReviewing = reviewingActionId.startsWith(`${submission.id}:`);
  const hideEditAction = !canMutate;

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
        {canValidate && submission.status === "submitted" ? (
          <Button
            onClick={() => onOpenValidationPrompt(submission)}
            size="sm"
            type="button"
            variant="outline"
          >
            <Sparkles className="size-4" />
            Validate version
          </Button>
        ) : null}
        {canMutate && submission.status === "rejected" ? (
          <Button
            onClick={() => onOpenFixPrompt(submission)}
            size="sm"
            type="button"
            variant="outline"
          >
            <Sparkles className="size-4" />
            Fix with AI
          </Button>
        ) : null}
        {canReview && submission.status === "submitted" ? (
          <>
            <Button
              disabled={isReviewing}
              onClick={() =>
                onReviewAction(submission, canPublish ? "approve_publish" : "approve")
              }
              size="sm"
              type="button"
            >
              <CheckCircle2 className="size-4" />
              {canPublish ? "Approve & publish" : "Approve"}
            </Button>
            <Button
              disabled={isReviewing}
              onClick={() => onReviewAction(submission, "reject")}
              size="sm"
              type="button"
              variant="destructive"
            >
              <XCircle className="size-4" />
              Reject
            </Button>
          </>
        ) : null}
        {canPublish && submission.status === "approved" ? (
          <Button
            disabled={isReviewing}
            onClick={() => onReviewAction(submission, "publish")}
            size="sm"
            type="button"
          >
            <FileCheck2 className="size-4" />
            Publish
          </Button>
        ) : null}
        {!hideEditAction ? (
          <Button asChild size="sm">
            <Link
              href={
                isEditable
                  ? submitHref({ submission: submission.id }, returnTo)
                  : submitHref({ submission: submission.id, version: "new" }, returnTo)
              }
            >
              {isEditable ? <Pencil className="size-4" /> : <Plus className="size-4" />}
              {isEditable ? "Edit" : "New version"}
            </Link>
          </Button>
        ) : null}
        {canMutate && isDeleteable ? (
          <Button
            aria-label={`Delete ${submission.name} ${submission.version}`}
            disabled={deleting || isReviewing}
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
  archivingName,
  canManageSubmissions,
  canPublish,
  canValidate,
  canReview,
  currentUserId,
  deletingId,
  group,
  onArchive,
  onDelete,
  onOpenFixPrompt,
  onOpenValidationPrompt,
  onReviewAction,
  reviewingActionId,
}: {
  archivingName: string;
  canManageSubmissions: boolean;
  canPublish: boolean;
  canValidate: boolean;
  canReview: boolean;
  currentUserId: string;
  deletingId: string;
  group: SubmissionGroup;
  onArchive: (serverName: string) => void;
  onDelete: (submission: SubmissionRead) => void;
  onOpenFixPrompt: (submission: SubmissionRead) => void;
  onOpenValidationPrompt: (submission: SubmissionRead) => void;
  onReviewAction: (
    submission: SubmissionRead,
    action: "approve" | "approve_publish" | "reject" | "publish",
  ) => void;
  reviewingActionId: string;
}) {
  const versionCount = group.submissions.length;
  const canArchiveServer = canPublish && group.submissions.some((item) => item.status === "published");
  const iconUrl =
    submissionIconUrl(group.latest) ||
    group.submissions.map(submissionIconUrl).find(Boolean) ||
    "";

  return (
    <article className="grid gap-4 rounded-lg border border-border bg-white p-4 shadow-[var(--shadow-card)] transition-shadow hover:shadow-[0_8px_24px_rgb(15_23_42_/_7%)]">
      <div className="grid min-w-0 gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
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
        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          {canArchiveServer ? (
            <Button
              disabled={archivingName === group.name}
              onClick={() => onArchive(group.name)}
              size="sm"
              type="button"
              variant="destructive"
            >
              <Archive className="size-4" />
              {archivingName === group.name ? "Archiving" : "Archive server"}
            </Button>
          ) : null}
        </div>
      </div>

      <div className="grid gap-2">
        {group.submissions.map((submission) => {
          const canMutate = canManageSubmissions || submission.submitterUserId === currentUserId;
          return (
            <VersionSubmissionRow
              canMutate={canMutate}
              canPublish={canPublish}
              canValidate={canValidate}
              canReview={canReview}
              deleting={deletingId === submission.id}
              key={submission.id}
              onDelete={onDelete}
              onOpenFixPrompt={onOpenFixPrompt}
              onOpenValidationPrompt={onOpenValidationPrompt}
              onReviewAction={onReviewAction}
              reviewingActionId={reviewingActionId}
              submission={submission}
            />
          );
        })}
      </div>
    </article>
  );
}

function SubmissionsPageContent() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const filter = statusFilterFromQuery(searchParams.get("status"));
  const page = pageFromQuery(searchParams.get("page"));
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [archivingName, setArchivingName] = useState("");
  const [deletingId, setDeletingId] = useState("");
  const [reviewingActionId, setReviewingActionId] = useState("");
  const [fixPromptSubmission, setFixPromptSubmission] = useState<SubmissionRead | null>(null);
  const [validationPromptSubmission, setValidationPromptSubmission] =
    useState<SubmissionRead | null>(null);
  const [user, setUser] = useState<UserRead | null>(null);
  const [submissions, setSubmissions] = useState<SubmissionRead[]>([]);
  const [metadata, setMetadata] = useState<SubmissionListMetadata | null>(null);
  const [statusCounts, setStatusCounts] =
    useState<Required<SubmissionStatusCounts>>(emptyStatusCounts);

  useEffect(() => {
    let active = true;
    const timeoutId = window.setTimeout(() => {
      setState("loading");
      setError("");
      Promise.all([
        currentUser(),
        listSubmissions({
          page,
          perPage: SUBMISSIONS_PAGE_SIZE,
          status: filter === "all" ? undefined : filter,
        }),
      ])
        .then(([current, response]) => {
          if (!active) return;
          setUser(current);
          setSubmissions(
            sortSubmissions(
              response.submissions.filter((submission) => {
                return canReviewSubmissions(current) || submission.submitterUserId === current.id;
              }),
            ),
          );
          setMetadata(response.metadata);
          setStatusCounts({ ...emptyStatusCounts, ...response.statusCounts });
          setState("ready");
        })
        .catch((caught) => {
          if (!active) return;
          setError(caught instanceof Error ? caught.message : "Unable to load submissions.");
          setState(caught instanceof HubApiError && caught.status === 401 ? "auth" : "error");
        });
    }, 0);
    return () => {
      active = false;
      window.clearTimeout(timeoutId);
    };
  }, [filter, page]);

  const counts = statusCounts;
  const groupedSubmissions = useMemo(() => groupSubmissionsByServer(submissions), [submissions]);
  const visibleStatusFilters = useMemo(() => {
    return statusOrder.filter((status) => (counts[status] ?? 0) > 0 || filter === status);
  }, [counts, filter]);
  const totalSubmissions = metadata?.total ?? submissions.length;
  const totalPages = metadata?.pages ?? 0;
  const firstVisibleSubmission =
    metadata && metadata.total > 0 ? (metadata.page - 1) * metadata.perPage + 1 : 0;
  const lastVisibleSubmission = metadata
    ? Math.min(metadata.page * metadata.perPage, metadata.total)
    : submissions.length;

  function filterHref(nextFilter: StatusFilter) {
    const nextParams = new URLSearchParams(searchParams.toString());
    if (nextFilter === "all") {
      nextParams.delete("status");
    } else {
      nextParams.set("status", nextFilter);
    }
    nextParams.delete("page");
    const queryString = nextParams.toString();
    return queryString ? `${pathname}?${queryString}` : pathname;
  }

  function pageHref(nextPage: number) {
    const nextParams = new URLSearchParams(searchParams.toString());
    if (nextPage <= 1) {
      nextParams.delete("page");
    } else {
      nextParams.set("page", String(nextPage));
    }
    const queryString = nextParams.toString();
    return queryString ? `${pathname}?${queryString}` : pathname;
  }

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

  async function handleArchiveServer(serverName: string) {
    if (!canPublishSubmissions(user)) return;
    const confirmed = window.confirm(
      `Archive published server ${serverName}? It will be removed from the public catalog.`,
    );
    if (!confirmed) return;

    setArchivingName(serverName);
    setActionError("");
    try {
      await archiveServer(serverName);
      setSubmissions((current) =>
        current.filter(
          (item) => item.name !== serverName || item.status !== "published",
        ),
      );
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "Unable to archive server.");
    } finally {
      setArchivingName("");
    }
  }

  async function handleReviewAction(
    submission: SubmissionRead,
    action: "approve" | "approve_publish" | "reject" | "publish",
  ) {
    if (!canUseReviewActions(user)) return;

    const message =
      action === "reject" ? window.prompt("Rejection message", submission.rejectionMessage) : "";
    if (action === "reject" && !message) return;

    setReviewingActionId(`${submission.id}:${action}`);
    setActionError("");
    try {
      const updated =
        action === "reject"
          ? await rejectSubmission(submission.id, { message: message ?? "" })
          : action === "approve_publish"
            ? await submissionAction(
                (await submissionAction(submission.id, "approve")).id,
                "publish",
              )
            : await submissionAction(submission.id, action);
      setSubmissions((current) =>
        sortSubmissions(current.map((item) => (item.id === updated.id ? updated : item))),
      );
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "Review action failed.");
    } finally {
      setReviewingActionId("");
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
          {state === "ready" ? (
            <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <div className="grid gap-1">
                <h1 className="flex items-center gap-2 text-3xl font-black tracking-normal text-foreground">
                  <FileCheck2 className="size-6 text-muted-foreground" />
                  <span>Submission review</span>
                </h1>
                <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                  Track MCP server drafts, reviews, and published versions.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <AddSubmissionMenu />
              </div>
            </header>
          ) : null}

          <section className="grid gap-4">
            {state === "ready" && actionError ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {actionError}
              </div>
            ) : null}
            {state === "ready" ? (
              <div className="flex flex-col gap-3 rounded-lg border border-border bg-white px-3 py-3 shadow-[var(--shadow-card)] lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="mr-1 text-sm font-bold text-foreground">
                  {groupedSubmissions.length}{" "}
                  {groupedSubmissions.length === 1 ? "server" : "servers"}
                  <span className="ml-1 text-muted-foreground">
                    / {totalSubmissions}{" "}
                    {totalSubmissions === 1 ? "submission" : "submissions"}
                  </span>
                </span>
                <Link
                  className={cn(
                    "inline-flex min-h-9 items-center gap-2 rounded-md border px-3 text-sm font-bold",
                    filter === "all"
                      ? "border-slate-900 bg-slate-900 text-white"
                      : "border-border bg-white text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                  href={filterHref("all")}
                  replace
                  scroll={false}
                >
                  All
                  <span className="rounded bg-white/15 px-1.5 text-xs">{counts.all ?? 0}</span>
                </Link>
                {visibleStatusFilters.map((status) => (
                  <Link
                    className={cn(
                      "inline-flex min-h-9 items-center gap-2 rounded-md border px-3 text-sm font-bold",
                      filter === status
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-border bg-white text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                    href={filterHref(status)}
                    key={status}
                    replace
                    scroll={false}
                  >
                    {statusMeta[status].label}
                    <span className="rounded bg-current/10 px-1.5 text-xs">
                      {counts[status] ?? 0}
                    </span>
                  </Link>
                ))}
              </div>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <CalendarClock className="size-4" />
                {metadata && metadata.total > 0
                  ? `Showing ${firstVisibleSubmission}-${lastVisibleSubmission} of ${metadata.total}`
                  : "Sorted by latest update"}
              </div>
              </div>
            ) : null}

            {state === "loading" ? (
              <ProtectedRouteState status="loading" />
            ) : null}
            {state === "auth" ? (
              <ProtectedRouteState signInHref="/login?next=submissions" status="auth" />
            ) : null}
            {state === "error" ? (
              <StatePanel detail={error} icon={AlertCircle} title="Unable to load submissions" tone="danger" />
            ) : null}
            {state === "ready" && (counts.all ?? 0) === 0 ? (
              <StatePanel
                action={<AddSubmissionMenu />}
                detail="Create the first registry submission for a server or version."
                icon={FileCheck2}
                title="No submissions yet"
              />
            ) : null}
            {state === "ready" && (counts.all ?? 0) > 0 && totalSubmissions === 0 ? (
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
                    archivingName={archivingName}
                    canManageSubmissions={Boolean(user?.is_superuser)}
                    canPublish={canPublishSubmissions(user)}
                    canValidate={canReviewSubmissions(user)}
                    canReview={canUseReviewActions(user)}
                    currentUserId={user?.id ?? ""}
                    deletingId={deletingId}
                    group={group}
                    key={group.name}
                    onArchive={handleArchiveServer}
                    onDelete={handleDeleteSubmission}
                    onOpenFixPrompt={setFixPromptSubmission}
                    onOpenValidationPrompt={setValidationPromptSubmission}
                    onReviewAction={handleReviewAction}
                    reviewingActionId={reviewingActionId}
                  />
                ))}
                {metadata && totalPages > 1 ? (
                  <nav
                    aria-label="Submission pages"
                    className="flex flex-col gap-2 rounded-lg border border-border bg-white px-3 py-3 shadow-[var(--shadow-card)] sm:flex-row sm:items-center sm:justify-between"
                  >
                    <span className="text-sm font-medium text-muted-foreground">
                      Page {metadata.page} of {totalPages}
                    </span>
                    <div className="flex items-center gap-2">
                      <Link
                        aria-disabled={metadata.page <= 1}
                        className={cn(
                          "inline-flex min-h-9 items-center gap-2 rounded-md border px-3 text-sm font-bold",
                          metadata.page <= 1
                            ? "pointer-events-none border-border bg-muted text-muted-foreground/60"
                            : "border-border bg-white text-foreground hover:bg-muted",
                        )}
                        href={pageHref(metadata.page - 1)}
                        replace
                        scroll={false}
                      >
                        <ChevronLeft className="size-4" />
                        Previous
                      </Link>
                      <Link
                        aria-disabled={metadata.page >= totalPages}
                        className={cn(
                          "inline-flex min-h-9 items-center gap-2 rounded-md border px-3 text-sm font-bold",
                          metadata.page >= totalPages
                            ? "pointer-events-none border-border bg-muted text-muted-foreground/60"
                            : "border-border bg-white text-foreground hover:bg-muted",
                        )}
                        href={pageHref(metadata.page + 1)}
                        replace
                        scroll={false}
                      >
                        Next
                        <ChevronRight className="size-4" />
                      </Link>
                    </div>
                  </nav>
                ) : null}
              </div>
            ) : null}
          </section>
        </div>
      </main>
      <AiValidationPromptDialog
        onOpenChange={(open) => {
          if (!open) setValidationPromptSubmission(null);
        }}
        open={Boolean(validationPromptSubmission)}
        serverName={validationPromptSubmission?.name ?? ""}
        submissionIds={validationPromptSubmission ? [validationPromptSubmission.id] : []}
        version={validationPromptSubmission?.version ?? ""}
      />
      <AiDraftFixPromptDialog
        errorMessage={fixPromptSubmission?.rejectionMessage ?? ""}
        onOpenChange={(open) => {
          if (!open) setFixPromptSubmission(null);
        }}
        open={Boolean(fixPromptSubmission)}
        serverName={fixPromptSubmission?.name ?? ""}
        submissionId={fixPromptSubmission?.id ?? ""}
      />
    </>
  );
}

export default function SubmissionsPage() {
  return (
    <Suspense fallback={null}>
      <SubmissionsPageContent />
    </Suspense>
  );
}
