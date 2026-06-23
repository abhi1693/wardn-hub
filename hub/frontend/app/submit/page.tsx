"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowLeft, CheckCircle2, Database, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  HubApiError,
  createSubmission,
  currentUser,
  submissionAction,
} from "@/lib/api/hub";
import type { SubmissionRead, UserRead } from "@/lib/api/generated/model";

const SERVER_SCHEMA_URL =
  "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json";

type TargetType = "package" | "remote";

export default function SubmitServerPage() {
  const [user, setUser] = useState<UserRead | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [targetType, setTargetType] = useState<TargetType>("package");
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState<SubmissionRead | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    currentUser()
      .then((response) => setUser(response))
      .catch(() => setUser(null))
      .finally(() => setAuthChecked(true));
  }, []);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitted(null);
    setIsSubmitting(true);

    const formData = new FormData(event.currentTarget);
    const version = String(formData.get("version") ?? "").trim();
    const repositoryUrl = String(formData.get("repositoryUrl") ?? "").trim();
    const websiteUrl = String(formData.get("websiteUrl") ?? "").trim();
    const packageIdentifier = String(formData.get("packageIdentifier") ?? "").trim();
    const remoteUrl = String(formData.get("remoteUrl") ?? "").trim();

    const serverJson = {
      "$schema": SERVER_SCHEMA_URL,
      name: String(formData.get("name") ?? "").trim(),
      title: String(formData.get("title") ?? "").trim(),
      description: String(formData.get("description") ?? "").trim(),
      version,
      ...(websiteUrl ? { websiteUrl } : {}),
      ...(repositoryUrl ? { repository: { url: repositoryUrl } } : {}),
      packages:
        targetType === "package"
          ? [
              {
                registryType: String(formData.get("registryType") ?? "npm"),
                identifier: packageIdentifier,
                version: String(formData.get("packageVersion") ?? "").trim() || version,
                transport: { type: String(formData.get("packageTransport") ?? "stdio") },
              },
            ]
          : [],
      remotes:
        targetType === "remote"
          ? [
              {
                type: String(formData.get("remoteTransport") ?? "streamable-http"),
                url: remoteUrl,
              },
            ]
          : [],
    };

    try {
      const draft = await createSubmission({
        submissionType: "new_server",
        serverJson,
      });
      const submittedRecord = await submissionAction(draft.id, "submit");
      setSubmitted(submittedRecord);
      event.currentTarget.reset();
      setTargetType("package");
    } catch (caught) {
      if (caught instanceof HubApiError) {
        setError(caught.message);
      } else {
        setError("Submission failed.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="min-h-dvh bg-background px-5 py-6">
      <div className="mx-auto grid w-full max-w-[900px] gap-5">
        <header className="flex min-h-10 items-center justify-between gap-4">
          <Link className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground" href="/">
            <ArrowLeft size={16} />
            Back to registry
          </Link>
          <div className="inline-flex items-center gap-2 text-sm font-semibold">
            <Database size={18} />
            Wardn Hub
          </div>
        </header>

        <Card>
          <CardHeader className="space-y-2">
            <CardTitle className="text-2xl">Submit MCP server</CardTitle>
            <CardDescription>
              Add a server document for review. Approved submissions become registry cards.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!authChecked && <p className="text-sm text-muted-foreground">Checking session.</p>}

            {authChecked && !user && (
              <div className="grid gap-4">
                <p className="text-sm text-muted-foreground">
                  Sign in to submit an MCP server for review.
                </p>
                <div>
                  <Button asChild>
                    <Link href="/login?next=submit">Sign in to submit</Link>
                  </Button>
                </div>
              </div>
            )}

            {authChecked && user && (
              <form className="grid gap-5" onSubmit={(event) => void handleSubmit(event)}>
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="grid gap-2">
                    <Label htmlFor="name">Server name</Label>
                    <Input
                      id="name"
                      name="name"
                      placeholder="io.github.example/weather"
                      required
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="version">Version</Label>
                    <Input id="version" name="version" placeholder="1.0.0" required />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="title">Title</Label>
                    <Input id="title" name="title" placeholder="Weather MCP" />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="websiteUrl">Website URL</Label>
                    <Input id="websiteUrl" name="websiteUrl" placeholder="https://example.com" type="url" />
                  </div>
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="description">Description</Label>
                  <textarea
                    className="min-h-24 w-full rounded-[var(--radius)] border border-input bg-card px-3 py-2 text-sm shadow-[var(--shadow-card)] outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25"
                    id="description"
                    name="description"
                    placeholder="Describe what tools this MCP server exposes and who it is for."
                    required
                  />
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="repositoryUrl">Repository URL</Label>
                  <Input
                    id="repositoryUrl"
                    name="repositoryUrl"
                    placeholder="https://github.com/example/weather-mcp"
                    type="url"
                  />
                </div>

                <fieldset className="grid gap-3 rounded-lg border border-border p-4">
                  <legend className="px-1 text-xs font-medium text-foreground">Target</legend>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant={targetType === "package" ? "default" : "outline"}
                      onClick={() => setTargetType("package")}
                    >
                      Package
                    </Button>
                    <Button
                      type="button"
                      variant={targetType === "remote" ? "default" : "outline"}
                      onClick={() => setTargetType("remote")}
                    >
                      Remote
                    </Button>
                  </div>

                  {targetType === "package" ? (
                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="grid gap-2">
                        <Label htmlFor="registryType">Registry</Label>
                        <select
                          className="h-9 rounded-[var(--radius)] border border-input bg-card px-3 text-sm shadow-[var(--shadow-card)] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25"
                          id="registryType"
                          name="registryType"
                        >
                          <option value="npm">npm</option>
                          <option value="pypi">PyPI</option>
                          <option value="mcpb">MCPB</option>
                          <option value="docker">Docker</option>
                        </select>
                      </div>
                      <div className="grid gap-2">
                        <Label htmlFor="packageIdentifier">Package identifier</Label>
                        <Input
                          id="packageIdentifier"
                          name="packageIdentifier"
                          placeholder="@example/weather-mcp"
                          required
                        />
                      </div>
                      <div className="grid gap-2">
                        <Label htmlFor="packageVersion">Package version</Label>
                        <Input id="packageVersion" name="packageVersion" placeholder="defaults to server version" />
                      </div>
                      <div className="grid gap-2">
                        <Label htmlFor="packageTransport">Transport</Label>
                        <select
                          className="h-9 rounded-[var(--radius)] border border-input bg-card px-3 text-sm shadow-[var(--shadow-card)] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25"
                          id="packageTransport"
                          name="packageTransport"
                        >
                          <option value="stdio">stdio</option>
                          <option value="streamable-http">streamable-http</option>
                          <option value="sse">sse</option>
                        </select>
                      </div>
                    </div>
                  ) : (
                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="grid gap-2">
                        <Label htmlFor="remoteUrl">Remote URL</Label>
                        <Input
                          id="remoteUrl"
                          name="remoteUrl"
                          placeholder="https://mcp.example.com"
                          required
                          type="url"
                        />
                      </div>
                      <div className="grid gap-2">
                        <Label htmlFor="remoteTransport">Transport</Label>
                        <select
                          className="h-9 rounded-[var(--radius)] border border-input bg-card px-3 text-sm shadow-[var(--shadow-card)] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25"
                          id="remoteTransport"
                          name="remoteTransport"
                        >
                          <option value="streamable-http">streamable-http</option>
                          <option value="sse">sse</option>
                        </select>
                      </div>
                    </div>
                  )}
                </fieldset>

                {error && <p className="text-sm text-destructive">{error}</p>}
                {submitted && (
                  <div className="flex items-start gap-2 rounded-lg border border-border bg-muted p-3 text-sm">
                    <CheckCircle2 className="mt-0.5 shrink-0" size={16} />
                    <div>
                      <strong className="block">Submission queued</strong>
                      <span className="text-muted-foreground">
                        {submitted.name} {submitted.version} is now {submitted.status}.
                      </span>
                    </div>
                  </div>
                )}

                <div className="flex justify-end">
                  <Button disabled={isSubmitting} type="submit">
                    <Send size={16} />
                    {isSubmitting ? "Submitting" : "Submit for review"}
                  </Button>
                </div>
              </form>
            )}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
