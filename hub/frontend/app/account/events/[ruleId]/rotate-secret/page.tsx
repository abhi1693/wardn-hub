"use client";

import Link from "next/link";
import { AlertCircle, RefreshCw, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { ProtectedRouteState } from "@/components/protected-route-state";
import { PublicHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { getEventRule, HubApiError, rotateEventRuleSecret } from "@/lib/api/hub";
import type { EventRuleRead } from "@/lib/api/generated/model";
import { actionUrl, hasSigningSecret, LoadState, SecretPanel } from "../../shared";

function stateFromError(error: unknown): LoadState {
  return error instanceof HubApiError && error.status === 401 ? "auth" : "error";
}

export default function RotateEventRuleSecretPage() {
  const params = useParams<{ ruleId: string }>();
  const ruleId = params.ruleId;
  const [state, setState] = useState<LoadState>("loading");
  const [rule, setRule] = useState<EventRuleRead | null>(null);
  const [error, setError] = useState("");
  const [rotating, setRotating] = useState(false);
  const [secret, setSecret] = useState("");

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

  async function rotateSecret() {
    if (!rule || !hasSigningSecret(rule)) return;
    setRotating(true);
    setError("");
    setSecret("");
    try {
      const response = await rotateEventRuleSecret(rule.id);
      setSecret(response.signingSecret);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to rotate signing secret.");
    } finally {
      setRotating(false);
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
                <RotateCcw className="size-6 text-muted-foreground" />
                <span>Rotate signing secret</span>
              </h1>
              <p className="text-sm leading-6 text-muted-foreground">
                Replace the webhook secret used to verify deliveries.
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
              {!hasSigningSecret(rule) ? (
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-900">
                  This rule does not have a signing secret to rotate.
                </div>
              ) : null}
              <div className="grid gap-2 rounded-lg border border-border bg-slate-50 p-4">
                <strong className="text-base text-foreground">{rule.name}</strong>
                <span className="break-all text-sm text-muted-foreground">{actionUrl(rule)}</span>
              </div>
              <SecretPanel secret={secret} />
              <div className="flex flex-wrap items-center justify-center gap-2">
                <Button
                  disabled={rotating || !hasSigningSecret(rule)}
                  onClick={() => void rotateSecret()}
                  type="button"
                >
                  {rotating ? <RefreshCw className="size-4" /> : <RotateCcw className="size-4" />}
                  {rotating ? "Rotating" : "Rotate secret"}
                </Button>
                <Button asChild disabled={rotating} type="button" variant="outline">
                  <Link href={`/account/events/${rule.id}`}>Back to rule</Link>
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
