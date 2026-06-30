"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Check, ClipboardCopy, FileText, KeyRound, X } from "lucide-react";
import type { ClipboardEvent } from "react";
import { useMemo, useRef, useState } from "react";

import {
  API_ACCESS_INSTRUCTIONS,
  ENVIRONMENT_REVIEW_RULES,
  PACKAGE_ARGUMENT_RULES,
  REMOTE_QUERY_PARAMETER_RULES,
  SOURCE_REVIEW_EVIDENCE_REQUIREMENTS,
  SOURCE_REVIEW_LIST_FORMAT,
  copyText,
  currentApiBaseUrl,
} from "@/components/ai-prompt-shared";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function parseRepositorySource(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return { repositoryUrl: "", subfolder: "" };

  const sshMatch = trimmed.match(/^git@github\.com:([^/]+)\/(.+?)(?:\.git)?$/i);
  if (sshMatch?.[1] && sshMatch?.[2]) {
    return {
      repositoryUrl: `${sshMatch[1]}/${sshMatch[2].replace(/\.git$/, "")}`,
      subfolder: "",
    };
  }

  try {
    const parsed = new URL(trimmed.startsWith("http") ? trimmed : `https://${trimmed}`);
    if (parsed.hostname.replace(/^www\./, "").toLowerCase() !== "github.com") {
      return { repositoryUrl: trimmed, subfolder: "" };
    }
    const pathParts = parsed.pathname.replace(/^\/+|\/+$/g, "").split("/").filter(Boolean);
    const [owner, repo] = pathParts;
    const viewMode = pathParts[2];
    if (!owner || !repo) return { repositoryUrl: trimmed, subfolder: "" };
    const hasRepositoryPath = viewMode === "tree" || viewMode === "blob";
    return {
      repositoryUrl: `${owner}/${repo.replace(/\.git$/, "")}`,
      subfolder: hasRepositoryPath ? pathParts.slice(4).join("/") : "",
    };
  } catch {
    const pathParts = trimmed
      .replace(/^\/+|\/+$/g, "")
      .split("/")
      .filter(Boolean);
    const [owner, repo] = pathParts;
    const viewMode = pathParts[2];
    if (!owner || !repo) return { repositoryUrl: trimmed, subfolder: "" };
    const hasRepositoryPath = viewMode === "tree" || viewMode === "blob";
    return {
      repositoryUrl: `${owner}/${repo.replace(/\.git$/, "")}`,
      subfolder: hasRepositoryPath ? pathParts.slice(4).join("/") : "",
    };
  }
}

function buildAiSubmissionPrompt(repositoryUrl: string, repositorySubfolder: string) {
  const sourceInfo = parseRepositorySource(repositoryUrl);
  const source = sourceInfo.repositoryUrl || "[repository URL or owner/repo]";
  const subfolder = repositorySubfolder.trim() || sourceInfo.subfolder;
  const subfolderLine = subfolder ? `\nRepository subfolder: ${subfolder}` : "";

  return `Submit this MCP server to Wardn Hub:

${source}${subfolderLine}

Wardn Hub API base URL: ${currentApiBaseUrl()}

${API_ACCESS_INSTRUCTIONS}

Complete the full flow:
1. Call POST /imports/server-source first with repositoryUrl and subfolder.
2. Do not stop after import.
3. Read the source README and any docs/files needed to verify install, launch, configuration, capabilities, limitations, and metadata.
4. Merge the importer output with details found in the source review.
5. Preserve imported package transport fields: command, args, env.
6. Submit the Wardn Hub draft with POST /submissions/submit.
7. If submit fails validation, fix the metadata and retry.
8. Do not stop at a draft unless required information cannot be found after source review.

Critical metadata rules:
- Do not use environment placeholder values that wrap names in dollar signs and braces.
- For secrets or user-specific values, use an empty string.
- Split package versions from identifiers.
- Do not put versions or tags inside package identifiers.
- Include optional variables too if they affect runtime, transport, auth, security, media/file access, tunnel mode, host/origin behavior, or feature flags.
- Do not create duplicate environment variable entries. If the same variable appears in multiple docs/import sources, merge it into one entry with the best description, default, required, secret, and source evidence.

${PACKAGE_ARGUMENT_RULES}

${REMOTE_QUERY_PARAMETER_RULES}

${ENVIRONMENT_REVIEW_RULES}

${SOURCE_REVIEW_EVIDENCE_REQUIREMENTS}

${SOURCE_REVIEW_LIST_FORMAT}

Before submitting, verify every documented env var and CLI argument from inspected sections is represented or explicitly listed in sourceReview.llm.unknowns with a reason.

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

  function applyRepositorySource(value: string) {
    const source = parseRepositorySource(value);
    setRepositoryUrl(source.repositoryUrl || value.trim());
    if (source.subfolder) {
      setRepositorySubfolder(source.subfolder);
    }
  }

  function pasteRepositorySource(event: ClipboardEvent<HTMLInputElement>) {
    const pastedValue = event.clipboardData.getData("text");
    const source = parseRepositorySource(pastedValue);
    if (
      source.repositoryUrl &&
      (source.repositoryUrl !== pastedValue.trim() || source.subfolder)
    ) {
      event.preventDefault();
      setRepositoryUrl(source.repositoryUrl);
      if (source.subfolder) {
        setRepositorySubfolder(source.subfolder);
      }
    }
  }

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) {
      setRepositoryUrl("");
      setRepositorySubfolder("");
      setCopyState("idle");
    }
    onOpenChange(nextOpen);
  }

  return (
    <Dialog.Root onOpenChange={handleOpenChange} open={open}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/45 backdrop-blur-[1px]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 grid max-h-[calc(100dvh-32px)] w-[calc(100vw-32px)] max-w-4xl -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-lg border border-border bg-white shadow-2xl focus-visible:outline-none">
          <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
            <div className="grid gap-1">
              <Dialog.Title className="flex items-center gap-2 text-xl font-black tracking-normal text-foreground">
                <KeyRound className="size-5 text-muted-foreground" />
                Submit from GitHub repo
              </Dialog.Title>
              <Dialog.Description className="text-sm text-muted-foreground">
                Copy a prompt that imports a repository, reviews source docs, creates a draft, and submits it.
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
                  onBlur={() => applyRepositorySource(repositoryUrl)}
                  onChange={(event) => setRepositoryUrl(event.target.value)}
                  onPaste={pasteRepositorySource}
                  placeholder="owner/repo or GitHub tree URL"
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
