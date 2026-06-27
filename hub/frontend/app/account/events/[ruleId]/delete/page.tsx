"use client";

import Link from "next/link";
import { AlertCircle, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { ProtectedRouteState } from "@/components/protected-route-state";
import { PublicHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { deleteEventRule, getEventRule, HubApiError } from "@/lib/api/hub";
import type { EventRuleRead } from "@/lib/api/generated/model";
import { actionUrl, LoadState } from "../../shared";

function stateFromError(error: unknown): LoadState {
  return error instanceof HubApiError && error.status === 401 ? "auth" : "error";
}

export default function DeleteEventRulePage() {
  const params = useParams<{ ruleId: string }>();
  const router = useRouter();
  const ruleId = params.ruleId;
  const [state, setState] = useState<LoadState>("loading");
  const [rule, setRule] = useState<EventRuleRead | null>(null);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    let active = true;
    getEventRule(ruleId)
      .then((response) => {
        if (!active) return;
        setRule(response);
        setState("ready");
      })
      .catch((caught) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "Unable to load event rule.");
        setState(stateFromError(caught));
      });
    return () => {
      active = false;
    };
  }, [ruleId]);

  async function removeRule() {
    if (!rule) return;
    setDeleting(true);
    setError("");
    try {
      await deleteEventRule(rule.id);
      router.push("/account/events");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to delete event rule.");
      setDeleting(false);
    }
  }

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
          {state === "ready" && rule ? (
            <header className="grid justify-items-center gap-3 text-center">
              <h1 className="flex items-center justify-center gap-2 text-3xl font-black tracking-normal text-foreground">
                <Trash2 className="size-6 text-muted-foreground" />
                <span>Delete event rule</span>
              </h1>
              <p className="text-sm leading-6 text-muted-foreground">
                Permanently remove this automation rule.
              </p>
            </header>
          ) : null}

          {state === "loading" ? <ProtectedRouteState status="loading" /> : null}
          {state === "auth" ? <ProtectedRouteState status="auth" /> : null}
          {state === "error" ? <ProtectedRouteState detail={error} status="error" /> : null}

          {state === "ready" && rule ? (
            <section className="grid gap-5 rounded-lg border border-border bg-white p-5 shadow-[var(--shadow-card)]">
              {error ? (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
                  {error}
                </div>
              ) : null}
              <div className="grid gap-2 rounded-lg border border-border bg-slate-50 p-4">
                <strong className="text-base text-foreground">{rule.name}</strong>
                <span className="break-all text-sm text-muted-foreground">{actionUrl(rule)}</span>
              </div>
              <div className="flex flex-wrap items-center justify-center gap-2">
                <Button
                  disabled={deleting}
                  onClick={() => void removeRule()}
                  type="button"
                  variant="destructive"
                >
                  {deleting ? <RefreshCw className="size-4" /> : <Trash2 className="size-4" />}
                  {deleting ? "Deleting" : "Delete rule"}
                </Button>
                <Button asChild disabled={deleting} type="button" variant="outline">
                  <Link href={`/account/events/${rule.id}`}>Cancel</Link>
                </Button>
              </div>
            </section>
          ) : null}

          {state === "error" ? <AlertCircle className="sr-only" /> : null}
        </div>
      </main>
    </>
  );
}
