"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Check, ClipboardCopy, FileText, Globe2, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import {
  API_ACCESS_INSTRUCTIONS,
  ENVIRONMENT_VARIABLE_RULES,
  PACKAGE_AND_REMOTE_RULES,
  PACKAGE_ARGUMENT_RULES,
  SOURCE_REVIEW_EVIDENCE_REQUIREMENTS,
  SOURCE_REVIEW_LIST_FORMAT,
  copyText,
  currentApiBaseUrl,
} from "@/components/ai-prompt-shared";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function normalizeUrl(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  try {
    return new URL(trimmed.startsWith("http") ? trimmed : `https://${trimmed}`).toString();
  } catch {
    return trimmed;
  }
}

function buildAiUrlDraftPrompt(sourceUrl: string) {
  const url = normalizeUrl(sourceUrl) || "[documentation URL]";

  return `Create a Wardn Hub draft from this MCP server documentation URL:

${url}

Wardn Hub API base URL: ${currentApiBaseUrl()}

${API_ACCESS_INSTRUCTIONS}

Goal:
- Read the documentation URL and create a draft with POST /submissions.
- Do not submit the draft for review.
- Return the draft submission ID and a concise summary of what was captured.

Important:
- Do not call POST /imports/server-source with the documentation URL. That endpoint only accepts GitHub source repositories.
- If the documentation identifies a GitHub source repository, you may use POST /imports/server-source with that repository to bootstrap metadata, but you must still read the documentation URL and merge any missing details before creating the draft.
- If the available docs are not enough to create a valid draft, do not create a draft. Report the missing fields instead.

Source review workflow:
1. Fetch and read the documentation URL.
2. Follow linked pages that are necessary for installation, transport, configuration, authentication, environment variables, CLI arguments, prerequisites, capabilities, limitations, package identifiers, remote endpoints, and source repository.
3. Prefer official docs, package manifests, README files, and source repository metadata over third-party summaries.
4. Record every inspected URL or source file in serverJson._meta.sourceReview.llm.filesRead.

Draft creation rules:
- Build a complete serverJson payload and create the draft with POST /submissions.
- Use submissionType "new_server" unless the docs clearly describe a new version of an existing Wardn Hub server.
- Use version "1.0.0" for a new server registry submission unless a Wardn registry version is explicitly known.
- Derive the server name from a verified source repository, official package, or official domain. If there is a GitHub repo, prefer io.github.owner/repo. If only official domain docs exist, use reverse-DNS style from the domain and product path.
- Set websiteUrl to the documentation URL unless a better official server page is identified.
- Set repository only when the source repository is known.
- Add icons only from official stable URLs.

${PACKAGE_AND_REMOTE_RULES}

${ENVIRONMENT_VARIABLE_RULES}

${PACKAGE_ARGUMENT_RULES}
- Add every documented CLI argument/configurable flag to serverJson._meta.sourceReview.llm.commandArguments even when it is not part of the default launch.

${SOURCE_REVIEW_EVIDENCE_REQUIREMENTS}

${SOURCE_REVIEW_LIST_FORMAT}

Before creating the draft:
- Validate the payload shape against the Wardn Hub API/OpenAPI schema if available.
- Ensure serverJson has title, description, documentation, websiteUrl, version, and at least one package or remote when the docs support it.
- Ensure all documented env vars, args, prerequisites, capabilities, and limitations from inspected docs are represented or explicitly listed in sourceReview.llm.unknowns with a reason.

Return:
- draft submission ID
- status
- server name
- registry version
- package or remote targets created
- environment variables included
- source URLs/files read
- any remaining unknowns`;
}

export function AiUrlDraftPromptDialog({
  onOpenChange,
  open,
}: {
  onOpenChange: (open: boolean) => void;
  open: boolean;
}) {
  const [sourceUrl, setSourceUrl] = useState("");
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const hasSourceUrl = Boolean(sourceUrl.trim());
  const prompt = useMemo(() => buildAiUrlDraftPrompt(sourceUrl), [sourceUrl]);

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
                <Globe2 className="size-5 text-muted-foreground" />
                Draft from docs URL
              </Dialog.Title>
              <Dialog.Description className="text-sm text-muted-foreground">
                Copy a prompt that reads official documentation and creates an unsubmitted draft.
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button aria-label="Close" size="icon" type="button" variant="ghost">
                <X className="size-4" />
              </Button>
            </Dialog.Close>
          </div>

          <div className="grid max-h-[calc(100dvh-154px)] gap-5 overflow-y-auto px-5 py-5">
            <div className="grid gap-2">
              <Label htmlFor="ai-url-draft-source">Documentation URL</Label>
              <Input
                autoFocus
                id="ai-url-draft-source"
                onBlur={() => setSourceUrl((value) => normalizeUrl(value))}
                onChange={(event) => setSourceUrl(event.target.value)}
                placeholder="https://cal.com/docs/mcp-server"
                value={sourceUrl}
              />
            </div>

            {hasSourceUrl ? (
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
                  className="min-h-[420px] resize-y rounded-[var(--radius)] border border-input bg-slate-50 px-3 py-3 font-mono text-xs leading-5 text-slate-800 outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25"
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
