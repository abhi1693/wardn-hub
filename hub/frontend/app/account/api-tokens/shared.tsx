"use client";

import Link from "next/link";
import {
  AlertCircle,
  Check,
  Clipboard,
  KeyRound,
  Pencil,
  Trash2,
} from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { UserAPITokenCreate, UserAPITokenRead } from "@/lib/api/generated/model";
import { cn } from "@/lib/utils";

export type LoadState = "loading" | "ready" | "error" | "auth";
export type APITokenScope = NonNullable<UserAPITokenCreate["scopes"]>[number];

export const TOKEN_CREATED_STORAGE_KEY = "wardn_hub_created_api_token";

export const scopeOptions: { description: string; label: string; value: APITokenScope }[] = [
  {
    description: "Read public catalog data.",
    label: "Catalog read",
    value: "catalog:read",
  },
  {
    description: "View your submissions.",
    label: "Submissions read",
    value: "submissions:read",
  },
  {
    description: "Create and update submissions.",
    label: "Submissions write",
    value: "submissions:write",
  },
  {
    description: "View token records.",
    label: "Tokens read",
    value: "tokens:read",
  },
  {
    description: "Create and manage tokens.",
    label: "Tokens write",
    value: "tokens:write",
  },
];

export const defaultScopes: APITokenScope[] = [
  "catalog:read",
  "submissions:read",
  "submissions:write",
];

export const readOnlyScopes: APITokenScope[] = [
  "catalog:read",
  "submissions:read",
  "tokens:read",
];

export function formatDate(value?: string | null) {
  if (!value) return "Never";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function scopeLabel(scope: string) {
  return scopeOptions.find((option) => option.value === scope)?.label ?? scope;
}

export function expiryToIso(value: string) {
  if (!value) return null;
  return new Date(`${value}T23:59:59`).toISOString();
}

export function isoToDateInput(value?: string | null) {
  if (!value) return "";
  return value.slice(0, 10);
}

export function isExpired(token: UserAPITokenRead) {
  return Boolean(token.expires_at && new Date(token.expires_at).getTime() <= Date.now());
}

export function tokenState(token: UserAPITokenRead) {
  if (!token.is_active) {
    return { className: "border-zinc-200 bg-zinc-50 text-zinc-700", label: "Inactive" };
  }
  if (isExpired(token)) {
    return { className: "border-red-200 bg-red-50 text-red-700", label: "Expired" };
  }
  return { className: "border-green-200 bg-green-50 text-green-700", label: "Active" };
}

export function sortTokens(tokens: UserAPITokenRead[]) {
  return [...tokens].sort(
    (left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime(),
  );
}

export function StatePanel({
  action,
  detail,
  icon: Icon = KeyRound,
  tone = "default",
  title,
}: {
  action?: React.ReactNode;
  detail: string;
  icon?: typeof KeyRound | typeof AlertCircle;
  tone?: "default" | "danger";
  title: string;
}) {
  return (
    <div
      className={cn(
        "grid min-h-72 place-items-center rounded-lg border border-dashed bg-white px-6 py-12 text-center shadow-[var(--shadow-card)]",
        tone === "danger" ? "border-red-200 bg-red-50/40" : "border-border",
      )}
    >
      <div className="grid max-w-md justify-items-center gap-4">
        <span
          className={cn(
            "inline-flex size-12 items-center justify-center rounded-full border",
            tone === "danger"
              ? "border-red-200 bg-white text-red-600"
              : "border-slate-200 bg-slate-50 text-slate-600",
          )}
        >
          <Icon className="size-5" />
        </span>
        <div className="grid gap-1">
          <h2 className="text-lg font-semibold text-foreground">{title}</h2>
          <p className="text-sm leading-6 text-muted-foreground">{detail}</p>
        </div>
        {action}
      </div>
    </div>
  );
}

export function TokenValuePanel({ token }: { token: string }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");

  async function copyToken() {
    setCopyError("");
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(token);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = token;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.left = "-9999px";
        document.body.appendChild(textarea);
        textarea.select();
        const copiedWithFallback = document.execCommand("copy");
        document.body.removeChild(textarea);
        if (!copiedWithFallback) throw new Error("copy command failed");
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopyError("Copy failed. Select the token and copy it manually.");
    }
  }

  return (
    <div className="grid gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="grid gap-1">
          <strong className="text-sm text-amber-950">Copy this token now.</strong>
          <span className="text-sm text-amber-800">It will not be shown again.</span>
        </div>
        <Button onClick={() => void copyToken()} size="sm" type="button" variant="outline">
          {copied ? <Check className="size-4" /> : <Clipboard className="size-4" />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <code className="block overflow-x-auto rounded-md border border-amber-200 bg-white px-3 py-2 text-sm text-amber-950">
        {token}
      </code>
      {copyError ? <span className="text-sm font-semibold text-amber-900">{copyError}</span> : null}
    </div>
  );
}

export function ScopeCheckbox({
  checked,
  description,
  label,
  onChange,
}: {
  checked: boolean;
  description: string;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-md border border-transparent px-2 py-3 transition-colors hover:border-slate-200 hover:bg-slate-50">
      <input
        checked={checked}
        className="mt-1 size-4"
        onChange={(event) => onChange(event.target.checked)}
        type="checkbox"
      />
      <span className="grid gap-1">
        <span className="text-sm font-bold text-foreground">{label}</span>
        <span className="text-sm leading-5 text-muted-foreground">{description}</span>
      </span>
    </label>
  );
}

export function TokenCard({ token }: { token: UserAPITokenRead }) {
  const state = tokenState(token);

  return (
    <article className="grid gap-4 rounded-lg border border-border bg-white p-4 shadow-[var(--shadow-card)] lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
      <div className="grid min-w-0 gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="inline-flex size-9 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-700">
            <KeyRound className="size-4" />
          </span>
          <strong className="min-w-0 overflow-hidden text-ellipsis text-base text-foreground">
            {token.name}
          </strong>
          <span className={cn("rounded-full border px-3 py-1 text-xs font-bold", state.className)}>
            {state.label}
          </span>
        </div>
        {token.description ? (
          <p className="text-sm leading-6 text-muted-foreground">{token.description}</p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <span className="font-semibold text-foreground">{token.token_prefix}</span>
          <span aria-hidden="true">/</span>
          <span>Created {formatDate(token.created_at)}</span>
          <span aria-hidden="true">/</span>
          <span>Last used {formatDate(token.last_used_at)}</span>
          <span aria-hidden="true">/</span>
          <span>Expires {formatDate(token.expires_at)}</span>
        </div>
        <div className="flex flex-wrap gap-2">
          {token.scopes.map((scope) => (
            <span
              className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-bold text-slate-700"
              key={scope}
            >
              {scopeLabel(scope)}
            </span>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 lg:justify-end">
        <Button asChild size="sm" variant="outline">
          <Link href={`/account/api-tokens/${token.id}/edit`}>
            <Pencil className="size-4" />
            Edit
          </Link>
        </Button>
        <Button asChild size="sm" variant="destructive">
          <Link href={`/account/api-tokens/${token.id}/delete`}>
            <Trash2 className="size-4" />
            Delete
          </Link>
        </Button>
      </div>
    </article>
  );
}
