"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Check, ClipboardCopy, FileText, KeyRound, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function currentApiBaseUrl() {
  if (typeof window === "undefined") return "/api/v1";
  return `${window.location.origin}/api/v1`;
}

function normalizeRepositoryReference(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return "";

  const sshMatch = trimmed.match(/^git@github\.com:([^/]+)\/(.+?)(?:\.git)?$/i);
  if (sshMatch?.[1] && sshMatch?.[2]) return `${sshMatch[1]}/${sshMatch[2]}`;

  try {
    const parsed = new URL(trimmed.startsWith("http") ? trimmed : `https://${trimmed}`);
    if (parsed.hostname.replace(/^www\./, "").toLowerCase() !== "github.com") return trimmed;
    const [owner, repo] = parsed.pathname.replace(/^\/+/, "").split("/");
    if (!owner || !repo) return trimmed;
    return `${owner}/${repo.replace(/\.git$/, "")}`;
  } catch {
    return trimmed;
  }
}

function buildAiSubmissionPrompt(repositoryUrl: string, repositorySubfolder: string) {
  const source = normalizeRepositoryReference(repositoryUrl) || "[repository URL or owner/repo]";
  const subfolder = repositorySubfolder.trim();
  const subfolderLine = subfolder ? `\nRepository subfolder: ${subfolder}` : "";

  return `Submit this MCP server to Wardn Hub:

${source}${subfolderLine}

Wardn Hub API base URL: ${currentApiBaseUrl()}

Required API access:
- Use WARDN_HUB_TOKEN as the Wardn Hub bearer token.
- If WARDN_HUB_TOKEN is not available in the environment or context, stop and ask the user for a Wardn Hub API token.
- Do not call the Wardn Hub API until a token is available.

Complete the full flow:
1. Call POST /imports/server-source first with repositoryUrl and subfolder.
2. Do not stop after import.
3. Read the source README and any docs/files needed to verify install, launch, configuration, capabilities, limitations, and metadata.
4. Merge the importer output with details found in the source review.
5. Preserve imported package transport fields: command, args, env.
6. Create the Wardn Hub draft with POST /submissions.
7. Submit the draft with POST /submissions/{id}/submit.
8. If submit fails validation, fix the draft and retry.
9. Do not stop at a draft unless required information cannot be found after source review.

Critical metadata rules:
- Do not use environment placeholder values that wrap names in dollar signs and braces.
- For secrets or user-specific values, use an empty string.
- Split package versions from identifiers.
- Do not put versions or tags inside package identifiers.
- Include optional variables too if they affect runtime, transport, auth, security, media/file access, tunnel mode, host/origin behavior, or feature flags.

Environment variable review:
- Read README/docs for every environment variable and CLI option.
- Do not only copy variables returned by import API.
- Add every documented environment variable to sourceReview.environmentVariables.
- If an environment variable belongs in runtime launch config, add it to packages[].transport.env.
- Use documented non-secret defaults when available.
- If you intentionally exclude a variable from packages[].transport.env, still include it in sourceReview.environmentVariables with source and reason.

Source review evidence must include:
- sourceReview.filesRead
- sourceReview.installCommands
- sourceReview.commandArguments
- sourceReview.environmentVariables
- sourceReview.prerequisites
- sourceReview.capabilitiesReviewed = true
- sourceReview.limitationsReviewed = true
- sourceReview.unknowns = []

Before submitting, verify every documented env var and CLI argument from inspected sections is represented or explicitly listed in sourceReview.unknowns with a reason.

Return:
- final submission ID
- status
- server name
- registry version
- package version
- validation status
- validation warnings/errors, if any
- list of env vars included`;
}

async function copyText(value: string, target?: HTMLTextAreaElement | null) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }
  } catch {
    // Some browsers expose clipboard but reject it on non-secure origins.
  }

  const textarea = target ?? document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "true");
  if (!target) {
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
  }

  try {
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    const copied = document.execCommand("copy");
    if (!copied) throw new Error("copy command failed");
  } finally {
    if (!target) document.body.removeChild(textarea);
  }
}

export function AiSubmissionPromptDialog({
  onOpenChange,
  open,
}: {
  onOpenChange: (open: boolean) => void;
  open: boolean;
}) {
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [repositorySubfolder, setRepositorySubfolder] = useState("");
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const hasRepository = Boolean(repositoryUrl.trim());
  const prompt = useMemo(
    () => buildAiSubmissionPrompt(repositoryUrl, repositorySubfolder),
    [repositorySubfolder, repositoryUrl],
  );

  async function copyPrompt() {
    setCopyState("idle");
    try {
      await copyText(prompt, promptRef.current);
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 1800);
    } catch {
      setCopyState("failed");
    }
  }

  return (
    <Dialog.Root onOpenChange={onOpenChange} open={open}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/45 backdrop-blur-[1px]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 grid max-h-[calc(100dvh-32px)] w-[calc(100vw-32px)] max-w-4xl -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-lg border border-border bg-white shadow-2xl focus-visible:outline-none">
          <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
            <div className="grid gap-1">
              <Dialog.Title className="flex items-center gap-2 text-xl font-black tracking-normal text-foreground">
                <KeyRound className="size-5 text-muted-foreground" />
                AI submission prompt
              </Dialog.Title>
              <Dialog.Description className="text-sm text-muted-foreground">
                Generate a copyable prompt for importing and submitting a server through the API.
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button aria-label="Close" size="icon" type="button" variant="ghost">
                <X className="size-4" />
              </Button>
            </Dialog.Close>
          </div>

          <div className="grid max-h-[calc(100dvh-154px)] gap-5 overflow-y-auto px-5 py-5">
            <div className="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(220px,1fr)]">
              <div className="grid gap-2">
                <Label htmlFor="ai-submission-repository">GitHub repository</Label>
                <Input
                  autoFocus
                  id="ai-submission-repository"
                  onBlur={() => setRepositoryUrl((value) => normalizeRepositoryReference(value))}
                  onChange={(event) => setRepositoryUrl(event.target.value)}
                  placeholder="owner/repo"
                  value={repositoryUrl}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="ai-submission-subfolder">Subfolder</Label>
                <Input
                  id="ai-submission-subfolder"
                  onChange={(event) => setRepositorySubfolder(event.target.value)}
                  placeholder="packages/server"
                  value={repositorySubfolder}
                />
              </div>
            </div>

            {hasRepository ? (
              <div className="grid gap-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <FileText className="size-4 text-muted-foreground" />
                    Prompt
                  </div>
                  <Button onClick={() => void copyPrompt()} type="button">
                    {copyState === "copied" ? (
                      <Check className="size-4" />
                    ) : (
                      <ClipboardCopy className="size-4" />
                    )}
                    {copyState === "copied" ? "Copied" : "Copy prompt"}
                  </Button>
                </div>
                <textarea
                  className="min-h-[360px] resize-y rounded-[var(--radius)] border border-input bg-slate-50 px-3 py-3 font-mono text-xs leading-5 text-slate-800 outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25"
                  readOnly
                  ref={promptRef}
                  value={prompt}
                />
                {copyState === "failed" ? (
                  <p className="text-sm font-medium text-destructive">
                    Copy failed. Select the prompt text and copy it manually.
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
