"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { AlertTriangle, Archive, FileCheck2, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { PublicHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { archiveServer, currentUser, deleteSubmission, getSubmission } from "@/lib/api/hub";
import type { SubmissionRead, UserRead } from "@/lib/api/generated/model";
import { cn } from "@/lib/utils";

type LoadState = "loading" | "ready" | "error";

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    : [];
}

function nestedRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringList(value: unknown) {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function readableReviewItem(value: unknown) {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";

  const record = value as Record<string, unknown>;
  const parts = [
    stringValue(record.flag),
    stringValue(record.name),
    stringValue(record.value),
    stringValue(record.default),
    stringValue(record.description),
  ].filter(Boolean);
  if (parts.length > 0) return parts.join(" - ");

  try {
    return JSON.stringify(record);
  } catch {
    return "";
  }
}

function reviewItemList(value: unknown) {
  return Array.isArray(value) ? value.map(readableReviewItem).filter(Boolean) : [];
}

function transportEnvironment(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.entries(value as Record<string, unknown>).map(([name, defaultValue]) => ({
    name,
    defaultValue: String(defaultValue ?? ""),
  }));
}

function formatDate(value?: string | null) {
  if (!value) return "Not set";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function statusClass(status: SubmissionRead["status"]) {
  switch (status) {
    case "approved":
    case "published":
      return "border-green-200 bg-green-50 text-green-700";
    case "rejected":
    case "withdrawn":
      return "border-red-200 bg-red-50 text-red-700";
    case "submitted":
      return "border-amber-200 bg-amber-50 text-amber-700";
    default:
      return "border-border bg-muted text-muted-foreground";
  }
}

function isDeleteableSubmission(status: SubmissionRead["status"]) {
  return status !== "published";
}

function canPublishSubmissions(user: UserRead | null) {
  return Boolean(user?.is_superuser);
}

function canMutateSubmission(user: UserRead | null, submission: SubmissionRead | null) {
  return Boolean(
    user?.is_superuser || (user && submission && submission.submitterUserId === user.id),
  );
}

export default function SubmissionDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const submissionId = params.id;
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [archiving, setArchiving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [submission, setSubmission] = useState<SubmissionRead | null>(null);
  const [user, setUser] = useState<UserRead | null>(null);

  useEffect(() => {
    currentUser()
      .then((response) => setUser(response))
      .catch(() => setUser(null));
  }, []);

  useEffect(() => {
    if (!submissionId) return;
    const timeoutId = window.setTimeout(() => {
      setState("loading");
      setError("");
      getSubmission(submissionId)
        .then((response) => {
          setSubmission(response);
          setState("ready");
        })
        .catch((caught) => {
          setError(caught instanceof Error ? caught.message : "Unable to load submission.");
          setState("error");
        });
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [submissionId]);

  const serverJson = submission?.serverJson ?? {};
  const title = stringValue(serverJson.title);
  const description = stringValue(serverJson.description);
  const documentation = stringValue(serverJson.documentation);
  const websiteUrl = stringValue(serverJson.websiteUrl);
  const validationResult = (submission?.validationResult ?? {}) as Record<string, unknown>;
  const validationStatus = stringValue(validationResult.status);
  const validationChecks = records(validationResult.checks).filter(
    (check) => stringValue(check.status) !== "passed",
  );
  const repository = serverJson.repository && typeof serverJson.repository === "object"
    ? (serverJson.repository as Record<string, unknown>)
    : null;
  const meta = nestedRecord(serverJson._meta);
  const sourceReview = nestedRecord(meta.sourceReview);
  const remotes = useMemo(() => records(serverJson.remotes), [serverJson.remotes]);
  const packages = useMemo(() => records(serverJson.packages), [serverJson.packages]);
  const filesRead = reviewItemList(sourceReview.filesRead);
  const installCommands = reviewItemList(sourceReview.installCommands);
  const commandArguments = reviewItemList(sourceReview.commandArguments);
  const prerequisites = reviewItemList(sourceReview.prerequisites);
  const reviewedEnvironmentVariables = records(sourceReview.environmentVariables);

  async function handleDeleteSubmission() {
    if (
      !submission ||
      !canMutateSubmission(user, submission) ||
      !isDeleteableSubmission(submission.status)
    ) {
      return;
    }
    const confirmed = window.confirm(
      `Delete submission ${submission.name} v${submission.version}? This cannot be undone.`,
    );
    if (!confirmed) return;

    setDeleting(true);
    setActionError("");
    try {
      await deleteSubmission(submission.id);
      router.push("/submissions");
      router.refresh();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "Unable to delete submission.");
    } finally {
      setDeleting(false);
    }
  }

  async function handleArchiveServer() {
    if (!submission || submission.status !== "published" || !canPublishSubmissions(user)) return;
    const confirmed = window.confirm(
      `Archive published server ${submission.name}? It will be removed from the public catalog.`,
    );
    if (!confirmed) return;

    setArchiving(true);
    setActionError("");
    try {
      await archiveServer(submission.name);
      router.push("/submissions");
      router.refresh();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "Unable to archive server.");
    } finally {
      setArchiving(false);
    }
  }

  return (
    <>
      <PublicHeader />
      <main className="min-h-[calc(100dvh-64px)] bg-background px-5 py-6">
      <div className="mx-auto grid w-full max-w-[var(--content-max-width)] gap-5">
        <div className="flex flex-wrap items-center justify-end gap-3">
          <div className="flex flex-wrap items-center gap-2">
            {submission ? (
              submission.status === "published" && canPublishSubmissions(user) ? (
                <Button
                  disabled={archiving}
                  onClick={() => void handleArchiveServer()}
                  type="button"
                  variant="destructive"
                >
                  <Archive className="size-4" />
                  {archiving ? "Archiving" : "Archive server"}
                </Button>
              ) : submission.status === "published" || !canMutateSubmission(user, submission) ? (
                null
              ) : (
                <Button asChild>
                  <Link href={`/submit?submission=${submission.id}`}>
                    Edit submission
                  </Link>
                </Button>
              )
            ) : null}
            <Button asChild variant="outline">
              <Link href="/submit">New submission</Link>
            </Button>
            {submission &&
            canMutateSubmission(user, submission) &&
            isDeleteableSubmission(submission.status) ? (
              <Button
                disabled={deleting}
                onClick={() => void handleDeleteSubmission()}
                type="button"
                variant="destructive"
              >
                <Trash2 className="size-4" />
                {deleting ? "Deleting" : "Delete submission"}
              </Button>
            ) : null}
          </div>
        </div>

        {actionError ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {actionError}
          </div>
        ) : null}

        <Card>
          <CardHeader className="flex items-start justify-between gap-4 space-y-0 md:flex-row">
            <div className="grid gap-1.5">
              <CardDescription className="flex items-center gap-2 uppercase">
                <FileCheck2 className="size-4" />
                Submission review
              </CardDescription>
              <CardTitle className="text-2xl">
                {submission?.name ?? "Loading submission"}
              </CardTitle>
            </div>
            {submission ? (
              <span
                className={cn(
                  "rounded-full border px-3 py-1 text-xs font-medium",
                  statusClass(submission.status),
                )}
              >
                {submission.status}
              </span>
            ) : null}
          </CardHeader>
          <CardContent>
            {state === "loading" ? (
              <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                Loading submission.
              </div>
            ) : null}
            {state === "error" ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            ) : null}
            {state === "ready" && submission ? (
              <div className="grid gap-5">
                <div className="grid gap-3 md:grid-cols-4">
                  <div className="rounded-md border bg-muted/30 p-3">
                    <div className="text-xs text-muted-foreground">Version</div>
                    <div className="font-medium">{submission.version}</div>
                  </div>
                  <div className="rounded-md border bg-muted/30 p-3">
                    <div className="text-xs text-muted-foreground">Type</div>
                    <div className="font-medium">{submission.submissionType}</div>
                  </div>
                  <div className="rounded-md border bg-muted/30 p-3">
                    <div className="text-xs text-muted-foreground">Submitted</div>
                    <div className="font-medium">{formatDate(submission.submittedAt)}</div>
                  </div>
                  <div className="rounded-md border bg-muted/30 p-3">
                    <div className="text-xs text-muted-foreground">Updated</div>
                    <div className="font-medium">{formatDate(submission.updatedAt)}</div>
                  </div>
                </div>

                {validationChecks.length > 0 ? (
                  <div className="grid gap-3 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                    <div className="flex items-center gap-2 font-semibold">
                      <AlertTriangle className="size-4" />
                      <span>
                        Validation {validationStatus || "warning"}
                      </span>
                    </div>
                    <div className="grid gap-2">
                      {validationChecks.map((check) => (
                        <div
                          className="rounded-md border border-amber-200 bg-white/60 px-3 py-2"
                          key={`${stringValue(check.name)}-${stringValue(check.message)}`}
                        >
                          <div className="font-semibold">{stringValue(check.name) || "Check"}</div>
                          <div>{stringValue(check.message) || stringValue(check.status)}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="grid gap-2">
                    <div className="text-sm font-medium">Title</div>
                    <div className="rounded-md border bg-card p-3 text-sm">{title || "Not provided"}</div>
                  </div>
                  <div className="grid gap-2">
                    <div className="text-sm font-medium">Website</div>
                    <div className="rounded-md border bg-card p-3 text-sm">{websiteUrl || "Not provided"}</div>
                  </div>
                  <div className="grid gap-2 md:col-span-2">
                    <div className="text-sm font-medium">Description</div>
                    <div className="rounded-md border bg-card p-3 text-sm">{description || "Not provided"}</div>
                  </div>
                  <div className="grid gap-2 md:col-span-2">
                    <div className="text-sm font-medium">Documentation</div>
                    <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md border bg-card p-3 text-sm">
                      {documentation || "Not provided"}
                    </pre>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="grid gap-2">
                    <div className="text-sm font-medium">Repository</div>
                    <div className="rounded-md border bg-card p-3 text-sm">
                      {repository
                        ? `${stringValue(repository.source) || "github"}:${stringValue(repository.url)}`
                        : "Not provided"}
                    </div>
                  </div>
                  <div className="grid gap-2">
                    <div className="text-sm font-medium">Targets</div>
                    <div className="rounded-md border bg-card p-3 text-sm">
                      {remotes.length} remote, {packages.length} package
                    </div>
                  </div>
                </div>

                {packages.length > 0 ? (
                  <div className="grid gap-3">
                    <div className="text-sm font-medium">Package details</div>
                    {packages.map((packageTarget, index) => {
                      const transport = nestedRecord(packageTarget.transport);
                      const transportArgs = stringList(transport.args);
                      const transportEnv = transportEnvironment(transport.env);
                      return (
                        <div
                          className="grid gap-3 rounded-md border bg-card p-3 text-sm"
                          key={`${stringValue(packageTarget.identifier)}-${index}`}
                        >
                          <div className="grid gap-3 md:grid-cols-4">
                            <div>
                              <div className="text-xs text-muted-foreground">Package</div>
                              <div className="font-medium">{stringValue(packageTarget.identifier) || "Not provided"}</div>
                            </div>
                            <div>
                              <div className="text-xs text-muted-foreground">Runtime</div>
                              <div className="font-medium">{stringValue(packageTarget.registryType) || "Not provided"}</div>
                            </div>
                            <div>
                              <div className="text-xs text-muted-foreground">Version</div>
                              <div className="font-medium">{stringValue(packageTarget.version) || "Not provided"}</div>
                            </div>
                            <div>
                              <div className="text-xs text-muted-foreground">Transport</div>
                              <div className="font-medium">{stringValue(transport.type) || "Not provided"}</div>
                            </div>
                          </div>
                          <div className="grid gap-3 md:grid-cols-2">
                            <div>
                              <div className="text-xs text-muted-foreground">Command</div>
                              <code className="block overflow-x-auto rounded border bg-muted/40 px-2 py-1">
                                {stringValue(transport.command) || "Not provided"}
                              </code>
                            </div>
                            <div>
                              <div className="text-xs text-muted-foreground">Arguments</div>
                              <code className="block overflow-x-auto rounded border bg-muted/40 px-2 py-1">
                                {transportArgs.length > 0 ? transportArgs.join(" ") : "Not provided"}
                              </code>
                            </div>
                          </div>
                          {transportEnv.length > 0 ? (
                            <div className="grid gap-2">
                              <div className="text-xs text-muted-foreground">Environment</div>
                              <div className="grid gap-2 md:grid-cols-2">
                                {transportEnv.map((envVar) => (
                                  <div className="rounded border bg-muted/20 px-2 py-1" key={envVar.name}>
                                    <div className="font-medium">{envVar.name}</div>
                                    <div className="text-xs text-muted-foreground">{envVar.defaultValue || "No default"}</div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                ) : null}

                {filesRead.length > 0 || installCommands.length > 0 || commandArguments.length > 0 ? (
                  <div className="grid gap-3 rounded-md border bg-card p-3 text-sm">
                    <div className="text-sm font-medium">Source review evidence</div>
                    <div className="grid gap-3 md:grid-cols-2">
                      <div>
                        <div className="text-xs text-muted-foreground">Files read</div>
                        <div>{filesRead.join(", ") || "Not provided"}</div>
                      </div>
                      <div>
                        <div className="text-xs text-muted-foreground">Command arguments reviewed</div>
                        <div>{commandArguments.join(" ") || "Not provided"}</div>
                      </div>
                    </div>
                    {installCommands.length > 0 ? (
                      <div>
                        <div className="text-xs text-muted-foreground">Install commands</div>
                        <pre className="overflow-auto whitespace-pre-wrap rounded border bg-muted/40 p-2">
                          {installCommands.join("\n")}
                        </pre>
                      </div>
                    ) : null}
                    {reviewedEnvironmentVariables.length > 0 ? (
                      <div>
                        <div className="text-xs text-muted-foreground">Reviewed environment variables</div>
                        <div className="grid gap-2 md:grid-cols-2">
                          {reviewedEnvironmentVariables.map((envVar) => (
                            <div className="rounded border bg-muted/20 px-2 py-1" key={stringValue(envVar.name)}>
                              <div className="font-medium">{stringValue(envVar.name)}</div>
                              <div className="text-xs text-muted-foreground">
                                Default: {stringValue(envVar.default) || "none"}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {prerequisites.length > 0 ? (
                      <div>
                        <div className="text-xs text-muted-foreground">Prerequisites</div>
                        <ul className="list-disc space-y-1 pl-5">
                          {prerequisites.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
          </CardContent>
        </Card>
        </div>
      </main>
    </>
  );
}
