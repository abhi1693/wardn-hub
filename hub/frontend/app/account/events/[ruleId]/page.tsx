"use client";

import Link from "next/link";
import { AlertCircle, BellRing, Pencil, Play, RotateCcw, Trash2, Webhook } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { ProtectedRouteState } from "@/components/protected-route-state";
import { PublicHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { getEventRule, HubApiError, listEventDeliveries } from "@/lib/api/hub";
import type { EventDeliveryRead, EventRuleRead } from "@/lib/api/generated/model";
import {
  actionUrl,
  DeliveryCard,
  EmptyPanel,
  formatDate,
  hasSigningSecret,
  LoadState,
} from "../shared";

function stateFromError(error: unknown): LoadState {
  return error instanceof HubApiError && error.status === 401 ? "auth" : "error";
}

export default function EventRuleDetailPage() {
  const params = useParams<{ ruleId: string }>();
  const ruleId = params.ruleId;
  const [state, setState] = useState<LoadState>("loading");
  const [rule, setRule] = useState<EventRuleRead | null>(null);
  const [deliveries, setDeliveries] = useState<EventDeliveryRead[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([
      getEventRule(ruleId),
      listEventDeliveries({ limit: 200, rule_id: ruleId }),
    ])
      .then(([ruleResponse, deliveryResponse]) => {
        if (!active) return;
        setRule(ruleResponse);
        setDeliveries(deliveryResponse.deliveries);
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
        <div className="mx-auto grid w-full max-w-4xl gap-5">
          {state === "ready" && rule ? (
            <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <div className="grid gap-1">
                <h1 className="flex items-center gap-2 text-3xl font-black tracking-normal text-foreground">
                  <BellRing className="size-6 text-muted-foreground" />
                  <span>{rule.name}</span>
                </h1>
                <p className="text-sm leading-6 text-muted-foreground">Event rule details.</p>
              </div>
            </header>
          ) : null}

          {state === "loading" ? <ProtectedRouteState status="loading" /> : null}
          {state === "auth" ? <ProtectedRouteState status="auth" /> : null}
          {state === "error" ? <ProtectedRouteState detail={error} status="error" /> : null}

          {state === "ready" && rule ? (
            <section className="grid gap-5">
              <article className="grid gap-5 rounded-lg border border-border bg-white p-5 shadow-[var(--shadow-card)]">
                <div className="flex items-center gap-2">
                  <Webhook className="size-5 text-muted-foreground" />
                  <h2 className="text-lg font-bold text-foreground">Webhook</h2>
                </div>
                <dl className="grid gap-4 text-sm md:grid-cols-2">
                  <div className="grid gap-1">
                    <dt className="font-bold text-foreground">Destination</dt>
                    <dd className="break-all text-muted-foreground">{actionUrl(rule)}</dd>
                  </div>
                  <div className="grid gap-1">
                    <dt className="font-bold text-foreground">Status</dt>
                    <dd className="text-muted-foreground">{rule.isEnabled ? "Enabled" : "Disabled"}</dd>
                  </div>
                  <div className="grid gap-1">
                    <dt className="font-bold text-foreground">Last triggered</dt>
                    <dd className="text-muted-foreground">{formatDate(rule.lastTriggeredAt)}</dd>
                  </div>
                  <div className="grid gap-1">
                    <dt className="font-bold text-foreground">Updated</dt>
                    <dd className="text-muted-foreground">{formatDate(rule.updatedAt)}</dd>
                  </div>
                </dl>
                {rule.description ? (
                  <p className="rounded-md bg-slate-50 p-3 text-sm text-muted-foreground">
                    {rule.description}
                  </p>
                ) : null}
                <div className="grid gap-2">
                  <h3 className="font-bold text-foreground">Subscribed events</h3>
                  <div className="flex flex-wrap gap-2">
                    {rule.eventTypes.map((eventType) => (
                      <span
                        className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-bold text-slate-700"
                        key={eventType}
                      >
                        {eventType}
                      </span>
                    ))}
                  </div>
                </div>
              </article>
              <div className="flex flex-wrap gap-2">
                <Button asChild variant="outline">
                  <Link href={`/account/events/${rule.id}/edit`}>
                    <Pencil className="size-4" />
                    Edit rule
                  </Link>
                </Button>
                <Button asChild variant="outline">
                  <Link href={`/account/events/${rule.id}/test`}>
                    <Play className="size-4" />
                    Test delivery
                  </Link>
                </Button>
                {hasSigningSecret(rule) ? (
                  <Button asChild variant="outline">
                    <Link href={`/account/events/${rule.id}/rotate-secret`}>
                      <RotateCcw className="size-4" />
                      Rotate secret
                    </Link>
                  </Button>
                ) : (
                  <Button disabled type="button" variant="outline">
                    <RotateCcw className="size-4" />
                    Rotate secret
                  </Button>
                )}
                <Button asChild variant="destructive">
                  <Link href={`/account/events/${rule.id}/delete`}>
                    <Trash2 className="size-4" />
                    Delete rule
                  </Link>
                </Button>
              </div>

              <section className="grid gap-3">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-lg font-bold text-foreground">Deliveries</h2>
                  <span className="text-sm text-muted-foreground">{deliveries.length} latest</span>
                </div>
                {deliveries.length === 0 ? (
                  <EmptyPanel
                    detail="Deliveries appear after this rule is created, tested, or matched by an event."
                    title="No deliveries"
                  />
                ) : (
                  <div className="grid gap-3">
                    {deliveries.map((delivery) => (
                      <DeliveryCard delivery={delivery} key={delivery.id} />
                    ))}
                  </div>
                )}
              </section>
            </section>
          ) : null}

          {state === "error" ? <AlertCircle className="sr-only" /> : null}
        </div>
      </main>
    </>
  );
}
