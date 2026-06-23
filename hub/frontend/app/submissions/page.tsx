"use client";

import Link from "next/link";
import { ArrowLeft, FileCheck2, Pencil, Plus } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { HubApiError, currentUser, listSubmissions } from "@/lib/api/hub";
import type { SubmissionRead } from "@/lib/api/generated/model";
import { cn } from "@/lib/utils";

type LoadState = "loading" | "ready" | "error" | "auth";

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

function isEditableSubmission(status: SubmissionRead["status"]) {
  return status !== "published";
}

export default function SubmissionsPage() {
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [submissions, setSubmissions] = useState<SubmissionRead[]>([]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setState("loading");
      setError("");
      Promise.all([currentUser(), listSubmissions()])
        .then(([current, response]) => {
          setSubmissions(
            response.submissions.filter((submission) => submission.submitterUserId === current.id),
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

  return (
    <main className="min-h-dvh bg-background px-5 py-6">
      <div className="mx-auto grid w-full max-w-5xl gap-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Button asChild variant="ghost">
            <Link href="/">
              <ArrowLeft className="size-4" />
              Back to registry
            </Link>
          </Button>
          <Button asChild>
            <Link href="/submit">
              <Plus className="size-4" />
              Submit server
            </Link>
          </Button>
        </div>

        <Card>
          <CardHeader>
            <div className="grid gap-1.5">
              <CardDescription className="flex items-center gap-2 uppercase">
                <FileCheck2 className="size-4" />
                My submissions
              </CardDescription>
              <CardTitle className="text-2xl">Submission review</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="grid gap-4">
            {state === "loading" ? (
              <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                Loading submissions.
              </div>
            ) : null}
            {state === "auth" ? (
              <div className="grid gap-3 rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                <div>Sign in to view your submissions.</div>
                <div>
                  <Button asChild size="sm">
                    <Link href="/login?next=submissions">Sign in</Link>
                  </Button>
                </div>
              </div>
            ) : null}
            {state === "error" ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            ) : null}
            {state === "ready" ? (
              <div className="grid gap-3">
                {submissions.length === 0 ? (
                  <div className="grid gap-3 rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                    <div>No submissions yet.</div>
                    <div>
                      <Button asChild size="sm">
                        <Link href="/submit">Submit server</Link>
                      </Button>
                    </div>
                  </div>
                ) : null}
                {submissions.map((submission) => (
                  <div
                    className="grid gap-3 rounded-md border bg-card p-4 text-foreground shadow-[var(--shadow-card)] hover:bg-muted/40 md:grid-cols-[minmax(0,1fr)_auto]"
                    key={submission.id}
                  >
                    <div className="grid gap-1">
                      <Link className="font-medium hover:underline" href={`/submissions/${submission.id}`}>
                        {submission.name}
                      </Link>
                      <div className="text-sm text-muted-foreground">
                        {submission.version} - {submission.submissionType} - updated{" "}
                        {formatDate(submission.updatedAt)}
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="flex items-center gap-2">
                        {isEditableSubmission(submission.status) ? (
                          <Button asChild aria-label={`Edit ${submission.name}`} size="icon" variant="outline">
                            <Link href={`/submit?submission=${submission.id}`} title="Edit submission">
                              <Pencil className="size-4" />
                            </Link>
                          </Button>
                        ) : (
                          <Button asChild aria-label={`Add version for ${submission.name}`} size="icon" variant="outline">
                            <Link href={`/submit?submission=${submission.id}&version=new`} title="Add version">
                              <Plus className="size-4" />
                            </Link>
                          </Button>
                        )}
                      </div>
                      <span
                        className={cn(
                          "rounded-full border px-3 py-1 text-xs font-medium",
                          statusClass(submission.status),
                        )}
                      >
                        {submission.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
