"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Check, ClipboardCopy, FileText, Globe2, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function currentApiBaseUrl() {
  if (typeof window === "undefined") return "/api/v1";
  return `${window.location.origin}/api/v1`;
}

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

Required API access:
- Use WARDN_HUB_TOKEN as the Wardn Hub bearer token.
- If WARDN_HUB_TOKEN is not available in the environment or context, stop and ask the user for a Wardn Hub API token.
- Do not call the Wardn Hub API until a token is available.

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
4. Record every inspected URL or source file in serverJson._meta.sourceReview.filesRead.

Draft creation rules:
- Build a complete serverJson payload and create the draft with POST /submissions.
- Use submissionType "new_server" unless the docs clearly describe a new version of an existing Wardn Hub server.
- Use version "1.0.0" for a new server registry submission unless a Wardn registry version is explicitly known.
- Derive the server name from a verified source repository, official package, or official domain. If there is a GitHub repo, prefer io.github.owner/repo. If only official domain docs exist, use reverse-DNS style from the domain and product path.
- Set websiteUrl to the documentation URL unless a better official server page is identified.
- Set repository only when the source repository is known.
- Add icons only from official stable URLs.

Package and remote rules:
- If the server is installed through npm, PyPI/uvx, Docker/OCI, or another package registry, add packages[] with registryType, identifier, version when known, and transport.
- Split versions from package identifiers. Do not put versions or tags inside identifiers.
- If the server is hosted remotely over HTTP/SSE/streamable HTTP and users connect to a URL instead of installing a package, add remotes[] instead of inventing a package target.
- Preserve documented command, args, transport type, env, and endpoint paths exactly enough for a user to configure the server.

Environment variable and argument rules:
- Do not use environment placeholder values that wrap names in dollar signs and braces.
- For secrets or user-specific values, use an empty string.
- Use documented non-secret defaults when available.
- Do not create duplicate environment variable entries. If the same variable appears in multiple docs/import sources, merge it into one entry with the best description, default, required, secret, and source evidence.
- Add every documented environment variable to serverJson._meta.sourceReview.environmentVariables, including optional variables that affect runtime, transport, auth, security, media/file access, tunnel mode, host/origin behavior, or feature flags.
- If an env var belongs in runtime launch config, add it to packages[].transport.env with a safe value.
- Treat packages[].transport.args as the concrete default launch command only. Do not put every documented option in transport.args.
- Add only arguments that must always be present for the documented default launch to packages[].transport.args, preserving order exactly.
- Put documented optional flags/configuration options in packages[].packageArguments with includeInLaunch false.
- Use packageArguments[].requiresValue true when a flag takes a user-supplied value. Do not put placeholder text like <port> or [url] in transport.args.
- requiresValue is a boolean. Do not set packageArguments[].value to placeholder examples such as "<host>", "[url]", "host", or "url".
- Do not include placeholders inside packageArguments[].flag. For docs that show "--host <host>", use {"flag":"--host","requiresValue":true,"includeInLaunch":false}.
- If a package argument is part of the default launch command, set includeInLaunch true. Otherwise leave it false.
- Add every documented CLI argument/configurable flag to serverJson._meta.sourceReview.commandArguments even when it is not part of the default launch.

Source review evidence must include:
- sourceReview.filesRead
- sourceReview.installCommands
- sourceReview.commandArguments
- sourceReview.environmentVariables
- sourceReview.prerequisites
- sourceReview.capabilitiesReviewed = true
- sourceReview.limitationsReviewed = true
- sourceReview.unknowns = []

Source review list format:
- filesRead, installCommands, commandArguments, and prerequisites must be readable strings or objects with at least one of: flag, name, value, default, description.
- Do not put arbitrary nested objects in commandArguments. For CLI options, prefer strings such as "--stdio" or objects like {"flag":"--port","requiresValue":true,"description":"Port for HTTP transport."}.

Before creating the draft:
- Validate the payload shape against the Wardn Hub API/OpenAPI schema if available.
- Ensure serverJson has title, description, documentation, websiteUrl, version, and at least one package or remote when the docs support it.
- Ensure all documented env vars, args, prerequisites, capabilities, and limitations from inspected docs are represented or explicitly listed in sourceReview.unknowns with a reason.

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
