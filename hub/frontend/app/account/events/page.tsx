"use client";

import Link from "next/link";
import { AlertCircle, BellRing, Plus, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ProtectedRouteState } from "@/components/protected-route-state";
import { PublicHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { HubApiError, listEventRules } from "@/lib/api/hub";
import type { EventRuleRead } from "@/lib/api/generated/model";
import {
  EmptyPanel,
  EVENT_RULE_SECRET_STORAGE_KEY,
  LoadState,
  RuleCard,
  SecretPanel,
} from "./shared";

function stateFromError(error: unknown): LoadState {
  return error instanceof HubApiError && error.status === 401 ? "auth" : "error";
}

export default function EventsPage() {
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [rules, setRules] = useState<EventRuleRead[]>([]);
  const [createdSecret] = useState(() => {
    if (typeof window === "undefined") return "";
    return window.sessionStorage.getItem(EVENT_RULE_SECRET_STORAGE_KEY) ?? "";
  });

  const sortedRules = useMemo(
    () => [...rules].sort((left, right) => left.name.localeCompare(right.name)),
    [rules],
  );

  async function refresh() {
    setState("loading");
    setError("");
    try {
      const rulesResponse = await listEventRules();
      setRules(rulesResponse.rules);
      setState("ready");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load events.");
      setState(stateFromError(caught));
    }
  }

  useEffect(() => {
    window.sessionStorage.removeItem(EVENT_RULE_SECRET_STORAGE_KEY);
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
          {state === "ready" ? (
            <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <div className="grid gap-1">
                <h1 className="flex items-center gap-2 text-3xl font-black tracking-normal text-foreground">
                  <BellRing className="size-6 text-muted-foreground" />
                  <span>Events</span>
                </h1>
                <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                  Manage signed webhook rules and delivery history.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => void refresh()} type="button" variant="outline">
                  <RefreshCw className="size-4" />
                  Refresh
                </Button>
                <Button asChild>
                  <Link href="/account/events/create">
                    <Plus className="size-4" />
                    Create rule
                  </Link>
                </Button>
              </div>
            </header>
          ) : null}

          {state === "loading" ? <ProtectedRouteState status="loading" /> : null}
          {state === "auth" ? <ProtectedRouteState status="auth" /> : null}
          {state === "error" ? (
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              <div className="flex items-center gap-2 font-semibold">
                <AlertCircle className="size-4" />
                <span>Unable to load events</span>
              </div>
              <p className="mt-1">{error || "Request failed."}</p>
            </div>
          ) : null}

          {state === "ready" && createdSecret ? <SecretPanel secret={createdSecret} /> : null}

          {state === "ready" ? (
            <section className="grid gap-6">
              <div className="grid gap-3">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-lg font-bold text-foreground">Rules</h2>
                  <span className="text-sm text-muted-foreground">{sortedRules.length} total</span>
                </div>
                {sortedRules.length === 0 ? (
                  <EmptyPanel detail="Create a webhook rule to receive events." title="No rules" />
                ) : (
                  <div className="grid gap-3">
                    {sortedRules.map((rule) => (
                      <RuleCard key={rule.id} rule={rule} />
                    ))}
                  </div>
                )}
              </div>
            </section>
          ) : null}
        </div>
      </main>
    </>
  );
}
