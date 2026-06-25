"use client";

import Link from "next/link";
import { AlertCircle, KeyRound, Plus, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { PublicHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { HubApiError, listApiTokens } from "@/lib/api/hub";
import type { UserAPITokenRead } from "@/lib/api/generated/model";
import {
  LoadState,
  sortTokens,
  StatePanel,
  TOKEN_CREATED_STORAGE_KEY,
  TokenCard,
  TokenValuePanel,
} from "./shared";

export default function ApiTokensPage() {
  const [state, setState] = useState<LoadState>("loading");
  const [tokens, setTokens] = useState<UserAPITokenRead[]>([]);
  const [error, setError] = useState("");
  const [createdToken] = useState(() => {
    if (typeof window === "undefined") return "";
    return window.sessionStorage.getItem(TOKEN_CREATED_STORAGE_KEY) ?? "";
  });

  const sortedTokens = useMemo(() => sortTokens(tokens), [tokens]);

  async function refresh() {
    setState("loading");
    setError("");
    try {
      const response = await listApiTokens();
      setTokens(response.tokens);
      setState("ready");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load API tokens.");
      setState(caught instanceof HubApiError && caught.status === 401 ? "auth" : "error");
    }
  }

  useEffect(() => {
    window.sessionStorage.removeItem(TOKEN_CREATED_STORAGE_KEY);
    const timeoutId = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timeoutId);
  }, []);

  return (
    <>
      <PublicHeader />
      <main
        className="min-h-[calc(100dvh-64px)] bg-[#f6f8fb] py-8"
        style={{
          paddingInline:
            "max(var(--content-gutter), calc((100vw - var(--content-max-width)) / 2 + var(--content-gutter)))",
        }}
      >
        <div className="grid gap-5">
          <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div className="grid gap-1">
              <h1 className="flex items-center gap-2 text-3xl font-black tracking-normal text-foreground">
                <KeyRound className="size-6 text-muted-foreground" />
                <span>API tokens</span>
              </h1>
              <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                Create and manage scoped bearer tokens for API access.
              </p>
            </div>
            <Button asChild>
              <Link href="/account/api-tokens/create">
                <Plus className="size-4" />
                Create token
              </Link>
            </Button>
          </header>

          {createdToken ? <TokenValuePanel token={createdToken} /> : null}

          {state === "loading" ? (
            <StatePanel
              detail="Fetching API token records for your account."
              icon={RefreshCw}
              title="Loading API tokens"
            />
          ) : null}
          {state === "auth" ? (
            <StatePanel
              action={
                <Button asChild size="sm">
                  <Link href="/login">Sign in</Link>
                </Button>
              }
              detail="Authentication is required before API tokens can be shown."
              icon={KeyRound}
              title="Sign in required"
            />
          ) : null}
          {state === "error" ? (
            <StatePanel
              detail={error || "Unable to load API tokens."}
              icon={AlertCircle}
              title="Unable to load API tokens"
              tone="danger"
            />
          ) : null}
          {state === "ready" && sortedTokens.length === 0 ? (
            <StatePanel
              action={
                <Button asChild size="sm">
                  <Link href="/account/api-tokens/create">
                    <Plus className="size-4" />
                    Create token
                  </Link>
                </Button>
              }
              detail="Create your first token to access the API outside the browser."
              icon={KeyRound}
              title="No API tokens yet"
            />
          ) : null}
          {state === "ready" && sortedTokens.length > 0 ? (
            <section className="grid gap-3">
              {sortedTokens.map((token) => (
                <TokenCard key={token.id} token={token} />
              ))}
            </section>
          ) : null}
        </div>
      </main>
    </>
  );
}
