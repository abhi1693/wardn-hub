"use client";

import Link from "next/link";
import { AlertCircle, KeyRound, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { PublicHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { HubApiError, deleteApiToken, listApiTokens } from "@/lib/api/hub";
import type { UserAPITokenRead } from "@/lib/api/generated/model";
import { formatDate, LoadState, StatePanel, tokenState } from "../../shared";
import { cn } from "@/lib/utils";

export default function DeleteApiTokenPage() {
  const params = useParams<{ tokenId: string }>();
  const router = useRouter();
  const tokenId = params.tokenId;
  const [state, setState] = useState<LoadState>("loading");
  const [token, setToken] = useState<UserAPITokenRead | null>(null);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    let active = true;
    listApiTokens()
      .then((response) => {
        if (!active) return;
        const record = response.tokens.find((item) => item.id === tokenId) ?? null;
        if (!record) {
          setState("error");
          setError("API token not found.");
          return;
        }
        setToken(record);
        setState("ready");
      })
      .catch((caught) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "Unable to load API token.");
        setState(caught instanceof HubApiError && caught.status === 401 ? "auth" : "error");
      });
    return () => {
      active = false;
    };
  }, [tokenId]);

  async function removeToken() {
    if (!token) return;
    setDeleting(true);
    setError("");
    try {
      await deleteApiToken(token.id);
      router.push("/account/api-tokens");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to delete API token.");
      setDeleting(false);
    }
  }

  const stateBadge = token ? tokenState(token) : null;

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
        <div className="mx-auto grid w-full max-w-3xl gap-5">
          <header className="grid justify-items-center gap-3 text-center">
            <div className="grid justify-items-center gap-1">
              <h1 className="flex items-center justify-center gap-2 text-3xl font-black tracking-normal text-foreground">
                <Trash2 className="size-6 text-muted-foreground" />
                <span>Delete API token</span>
              </h1>
              <p className="text-sm leading-6 text-muted-foreground">
                Permanently revoke a token from API access.
              </p>
            </div>
          </header>

          {state === "loading" ? (
            <StatePanel detail="Fetching API token details." icon={RefreshCw} title="Loading token" />
          ) : null}
          {state === "auth" ? (
            <StatePanel
              action={
                <Button asChild size="sm">
                  <Link href="/login">Sign in</Link>
                </Button>
              }
              detail="Authentication is required before API tokens can be deleted."
              icon={KeyRound}
              title="Sign in required"
            />
          ) : null}
          {state === "error" ? (
            <StatePanel
              detail={error || "Unable to load API token."}
              icon={AlertCircle}
              title="Unable to load token"
              tone="danger"
            />
          ) : null}
          {state === "ready" && token && stateBadge ? (
            <>
              {error ? (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
                  {error}
                </div>
              ) : null}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Trash2 className="size-4" />
                    Confirm deletion
                  </CardTitle>
                  <CardDescription>This action cannot be undone.</CardDescription>
                </CardHeader>
                <CardContent className="grid gap-5">
                  <div className="grid gap-3 rounded-lg border border-border bg-white p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <strong className="text-base text-foreground">{token.name}</strong>
                      <span
                        className={cn(
                          "rounded-full border px-3 py-1 text-xs font-bold",
                          stateBadge.className,
                        )}
                      >
                        {stateBadge.label}
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
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center justify-center gap-2">
                    <Button
                      disabled={deleting}
                      onClick={() => void removeToken()}
                      type="button"
                      variant="destructive"
                    >
                      {deleting ? <RefreshCw className="size-4" /> : <Trash2 className="size-4" />}
                      {deleting ? "Deleting" : "Delete token"}
                    </Button>
                    <Button asChild disabled={deleting} type="button" variant="outline">
                      <Link href="/account/api-tokens">Cancel</Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </>
          ) : null}
        </div>
      </main>
    </>
  );
}
