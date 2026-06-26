"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Check, ClipboardCheck, ClipboardCopy, ShieldCheck, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

function currentApiBaseUrl() {
  if (typeof window === "undefined") return "/api/v1";
  return `${window.location.origin}/api/v1`;
}

function buildAiValidationPrompt({
  serverName,
  submissionIds,
  version,
}: {
  serverName: string;
  submissionIds: string[];
  version: string;
}) {
  const idList = submissionIds.map((id) => `- ${id}`).join("\n");
  return `Validate one Wardn Hub MCP server version that is currently in review.

Wardn Hub API base URL: ${currentApiBaseUrl()}
Server: ${serverName}
Version: ${version || "unknown"}
In-review submission ID shown in UI:
${idList || "- none"}

Required API access:
- Use WARDN_HUB_TOKEN as the Wardn Hub bearer token.
- If WARDN_HUB_TOKEN is not available in the environment or context, stop and ask the user for a Wardn Hub API token.
- Do not call the Wardn Hub API until a token is available.
- The token must belong to an admin or moderator account with review-system access and must be able to read the submitted queue.
- The token must include submissions:read to inspect submissions and submissions:moderate to approve or reject submissions.
- To publish, the token must belong to a superuser and include submissions:publish.
- Moderator tokens may approve or reject submitted versions. Publishing and archiving require a superuser token.
- If GET /submissions does not expose submitted records for review, stop and report that the token does not have review access.
- Do not approve, reject, publish, update, or delete anything before presenting your validation report and receiving explicit user approval for the exact action.

Scope:
1. Validate only the in-review submission ID listed above.
2. Call GET /submissions/{id} before reviewing details.
3. Confirm the fetched submission has status "submitted", name "${serverName}", and version "${version || "the listed version"}". In the Wardn Hub UI, this status is shown as "In review".
4. Ignore any other submissions returned by the API, including drafts, approved submissions, rejected submissions, withdrawn submissions, published submissions, other versions, and submissions for other servers.
5. If the listed ID cannot be fetched as an in-review submission for this version, report that clearly and stop.

Validation workflow for each submission:
1. Read submission.serverJson, submission.validationResult, and submission.serverJson._meta.sourceReview.
2. Identify the source repository from serverJson.repository.url and any source links in documentation/package metadata.
3. Read the upstream README and relevant docs/files needed to verify installation, package transport, environment variables, CLI arguments, prerequisites, capabilities, limitations, and version/package metadata.
4. Compare the source review evidence against the upstream source. Do not assume importer output is complete.
5. Treat this as registry metadata review only. Do not add runtime installs, do not invoke MCP tools, and do not manage runtime infrastructure.

Required checks:
- Registry name, title, description, website, repository, version, icons, packages, remotes, and documentation are present and accurate where applicable.
- Package identifiers and versions are split correctly. No package identifier contains a version or tag.
- Transport command, args, env, and transport type match documented install/run instructions.
- No environment value uses placeholder syntax that wraps names in dollar signs and braces.
- Environment variable names are unique within each package target and within sourceReview.environmentVariables.
- Secret or user-specific defaults are empty strings.
- Every documented environment variable is represented in sourceReview.environmentVariables, including optional variables that affect runtime, transport, auth, security, media/file access, tunnel mode, host/origin behavior, or feature flags.
- Variables required at launch are also represented in packages[].transport.env with safe defaults.
- CLI arguments and configurable flags are represented in sourceReview.commandArguments and package transport args where appropriate.
- Prerequisites are represented in sourceReview.prerequisites.
- sourceReview.filesRead, installCommands, commandArguments, environmentVariables, prerequisites, capabilitiesReviewed, limitationsReviewed, and unknowns are complete.
- capabilitiesReviewed and limitationsReviewed are true.
- sourceReview.unknowns is empty unless there is a specific documented reason.
- validationResult has no failing checks that remain unresolved.

Report format:
- Submission ID
- Server name and version
- Repository/source files reviewed
- Decision: pass, needs fixes, or cannot validate
- Findings grouped by severity
- Missing or incorrect environment variables
- Missing or incorrect command arguments
- Suggested rejection message if the submission should be rejected
- Suggested approval note if the submission passes

After the report:
- Ask the user exactly what action to take using lettered options so they can reply with a single letter. If the token has moderator-only access, display:
  A. Approve
  B. Reject with the suggested message
  C. Leave unchanged
- If the token has superuser publishing access, display:
  A. Approve
  B. Approve and publish
  C. Reject with the suggested message
  D. Leave unchanged
- Do not take action from your own recommendation alone.
- Only after the user explicitly chooses one lettered option or the exact action text, call the corresponding Wardn Hub API endpoint.
- If the user chooses approve, call POST /submissions/{id}/approve.
- If the user chooses approve and publish, first call POST /submissions/{id}/approve, then call POST /submissions/{id}/publish on the approved submission. Only offer and perform this when the token has superuser publishing access.
- If the user chooses reject, call POST /submissions/{id}/reject with a clear message.
- Do not publish unless the user explicitly chose approve and publish.
- After performing an approved action, return the endpoints called, final submission status, and any API error.

Do not mark a submission as passing if source review evidence is incomplete, upstream docs mention an env var/argument/prerequisite that is missing, or package transport details cannot be verified.`;
}

async function copyText(value: string, target?: HTMLTextAreaElement | null) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }
  } catch {
    // Clipboard can be exposed but blocked on non-secure origins.
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

export function AiValidationPromptDialog({
  onOpenChange,
  open,
  serverName,
  submissionIds,
  version,
}: {
  onOpenChange: (open: boolean) => void;
  open: boolean;
  serverName: string;
  submissionIds: string[];
  version: string;
}) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const prompt = useMemo(
    () => buildAiValidationPrompt({ serverName, submissionIds, version }),
    [serverName, submissionIds, version],
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
                <ShieldCheck className="size-5 text-muted-foreground" />
                Validate version with AI
              </Dialog.Title>
              <Dialog.Description className="text-sm text-muted-foreground">
                Copy a review prompt for this in-review version.
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
                <ClipboardCheck className="size-4 text-muted-foreground" />
                {serverName || "Server"} {version ? `v${version}` : ""} review prompt
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
