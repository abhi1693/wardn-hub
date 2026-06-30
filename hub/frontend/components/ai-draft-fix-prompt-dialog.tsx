"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Check, ClipboardCopy, FileText, Wrench, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import {
  API_ACCESS_INSTRUCTIONS,
  DRAFT_METADATA_RULES,
  REGISTRY_METADATA_SCOPE_RULE,
  SOURCE_REVIEW_LIST_FORMAT,
  copyText,
  currentApiBaseUrl,
} from "@/components/ai-prompt-shared";
import { Button } from "@/components/ui/button";

function buildAiDraftFixPrompt({
  errorMessage,
  serverName,
  submissionId,
}: {
  errorMessage: string;
  serverName: string;
  submissionId: string;
}) {
  return `Fix this Wardn Hub draft so it can be submitted for review.

Wardn Hub API base URL: ${currentApiBaseUrl()}
Draft submission ID: ${submissionId}
Server name: ${serverName || "unknown"}
Current submit/review feedback: ${errorMessage || "unknown"}

${API_ACCESS_INSTRUCTIONS}

Goal:
- Fetch the draft with GET /submissions/${submissionId}.
- Validate the draft against the submit/review feedback and Wardn Hub review requirements.
- Read the upstream source/docs needed to fix missing or incomplete metadata.
- Update and submit the draft with POST /submissions/submit using submissionId "${submissionId}".
- If submission still fails, repeat the fix/update/submit loop until it passes or the required information cannot be found.

Important:
- Do not create a new submission. Fix this existing draft only.
- Do not guess source-review evidence. It must reflect URLs/files actually inspected.
- If the draft lacks enough source links to verify the server, stop and ask the user for the official repository or documentation URL.
- ${REGISTRY_METADATA_SCOPE_RULE}

Source review requirements:
- Fill serverJson._meta.sourceReview.llm.filesRead with every README/docs/source URL or file inspected.
- Fill sourceReview.llm.installCommands with documented install/run commands when package targets exist.
- Fill sourceReview.llm.commandArguments with documented CLI args/configurable flags.
- Fill sourceReview.llm.environmentVariables with every documented environment variable, including optional variables that affect runtime, transport, auth, security, media/file access, tunnel mode, host/origin behavior, or feature flags.
- Fill sourceReview.llm.prerequisites with required local apps, services, accounts, API keys, browser/runtime dependencies, or external services.
- Set sourceReview.llm.capabilitiesReviewed = true after reviewing documented capabilities/tools/features.
- Set sourceReview.llm.limitationsReviewed = true after reviewing documented limitations, caveats, unsupported behavior, risks, or operational requirements.
- Set sourceReview.llm.unknowns = [] only when all required source-review questions are resolved. Otherwise list specific unknowns and do not submit.

${SOURCE_REVIEW_LIST_FORMAT}

${DRAFT_METADATA_RULES}

Return:
- final submission ID
- final status
- source URLs/files read
- environment variables included
- command arguments included
- remaining validation warnings/errors, if any
- if you cannot fix it, the exact missing information needed from the user`;
}

export function AiDraftFixPromptDialog({
  errorMessage,
  onOpenChange,
  open,
  serverName,
  submissionId,
}: {
  errorMessage: string;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  serverName: string;
  submissionId: string;
}) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const prompt = useMemo(
    () => buildAiDraftFixPrompt({ errorMessage, serverName, submissionId }),
    [errorMessage, serverName, submissionId],
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
                <Wrench className="size-5 text-muted-foreground" />
                Fix draft with AI
              </Dialog.Title>
              <Dialog.Description className="text-sm text-muted-foreground">
                Copy a prompt that asks an LLM to repair this draft and retry review submission.
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button aria-label="Close" size="icon" type="button" variant="ghost">
                <X className="size-4" />
              </Button>
            </Dialog.Close>
          </div>

          <div className="grid max-h-[calc(100dvh-154px)] gap-4 overflow-y-auto px-5 py-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <FileText className="size-4 text-muted-foreground" />
                Draft repair prompt
              </div>
              <Button disabled={!submissionId} onClick={() => void copyPrompt()} type="button">
                {copyState === "copied" ? (
                  <Check className="size-4" />
                ) : (
                  <ClipboardCopy className="size-4" />
                )}
                {copyState === "copied" ? "Copied" : "Copy prompt"}
              </Button>
            </div>
            <textarea
              className="min-h-[520px] resize-y rounded-[var(--radius)] border border-input bg-slate-50 px-3 py-3 font-mono text-xs leading-5 text-slate-800 outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25"
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
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
