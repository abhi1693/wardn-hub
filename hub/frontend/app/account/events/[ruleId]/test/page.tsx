"use client";

import Link from "next/link";
import { AlertCircle, Play, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { ProtectedRouteState } from "@/components/protected-route-state";
import { PublicHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { getEventRule, HubApiError, testEventRule } from "@/lib/api/hub";
import type { EventRuleRead } from "@/lib/api/generated/model";
import { actionUrl, LoadState } from "../../shared";

function stateFromError(error: unknown): LoadState {
  return error instanceof HubApiError && error.status === 401 ? "auth" : "error";
}

export default function TestEventRulePage() {
  const params = useParams<{ ruleId: string }>();
  const router = useRouter();
  const ruleId = params.ruleId;
  const [state, setState] = useState<LoadState>("loading");
  const [rule, setRule] = useState<EventRuleRead | null>(null);
  const [error, setError] = useState("");
  const [testing, setTesting] = useState(false);

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

  async function createTestDelivery() {
    if (!rule) return;
    setTesting(true);
    setError("");
    try {
      const delivery = await testEventRule(rule.id);
      router.push(`/account/events/deliveries/${delivery.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create test delivery.");
      setTesting(false);
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
                <Play className="size-6 text-muted-foreground" />
                <span>Test event rule</span>
              </h1>
              <p className="text-sm leading-6 text-muted-foreground">
                Create a pending test delivery for this rule.
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
                <Button disabled={testing} onClick={() => void createTestDelivery()} type="button">
                  {testing ? <RefreshCw className="size-4" /> : <Play className="size-4" />}
                  {testing ? "Creating" : "Create test delivery"}
                </Button>
                <Button asChild disabled={testing} type="button" variant="outline">
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
