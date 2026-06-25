"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FileCheck2 } from "lucide-react";
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
import { getSubmission } from "@/lib/api/hub";
import type { SubmissionRead } from "@/lib/api/generated/model";
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

export default function SubmissionDetailPage() {
  const params = useParams<{ id: string }>();
  const submissionId = params.id;
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [submission, setSubmission] = useState<SubmissionRead | null>(null);

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
  const repository = serverJson.repository && typeof serverJson.repository === "object"
    ? (serverJson.repository as Record<string, unknown>)
    : null;
  const remotes = useMemo(() => records(serverJson.remotes), [serverJson.remotes]);
  const packages = useMemo(() => records(serverJson.packages), [serverJson.packages]);

  return (
    <>
      <PublicHeader />
      <main className="min-h-[calc(100dvh-64px)] bg-background px-5 py-6">
      <div className="mx-auto grid w-full max-w-[var(--content-max-width)] gap-5">
        <div className="flex flex-wrap items-center justify-end gap-3">
          <div className="flex flex-wrap items-center gap-2">
            {submission ? (
              submission.status === "published" ? (
                <Button asChild>
                  <Link href={`/submit?submission=${submission.id}&version=new`}>
                    Add new version
                  </Link>
                </Button>
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
          </div>
        </div>

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
              </div>
            ) : null}
          </CardContent>
        </Card>
        </div>
      </main>
    </>
  );
}
