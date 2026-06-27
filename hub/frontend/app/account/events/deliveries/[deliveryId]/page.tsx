"use client";

import Link from "next/link";
import { AlertCircle, BellRing, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { ProtectedRouteState } from "@/components/protected-route-state";
import { PublicHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { getEventDelivery, HubApiError } from "@/lib/api/hub";
import type { EventDeliveryRead } from "@/lib/api/generated/model";
import { formatDate, LoadState, statusTone } from "../../shared";
import { cn } from "@/lib/utils";

function stateFromError(error: unknown): LoadState {
  return error instanceof HubApiError && error.status === 401 ? "auth" : "error";
}

export default function EventDeliveryDetailPage() {
  const params = useParams<{ deliveryId: string }>();
  const deliveryId = params.deliveryId;
  const [state, setState] = useState<LoadState>("loading");
  const [delivery, setDelivery] = useState<EventDeliveryRead | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    getEventDelivery(deliveryId)
      .then((response) => {
        if (!active) return;
        setDelivery(response);
        setState("ready");
      })
      .catch((caught) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "Unable to load event delivery.");
        setState(stateFromError(caught));
      });
    return () => {
      active = false;
    };
  }, [deliveryId]);

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
          {state === "ready" && delivery ? (
            <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <div className="grid gap-1">
                <h1 className="flex items-center gap-2 text-3xl font-black tracking-normal text-foreground">
                  <BellRing className="size-6 text-muted-foreground" />
                  <span>Event delivery</span>
                </h1>
                <p className="text-sm leading-6 text-muted-foreground">
                  Webhook delivery status and response details.
                </p>
              </div>
            </header>
          ) : null}

          {state === "loading" ? <ProtectedRouteState status="loading" /> : null}
          {state === "auth" ? <ProtectedRouteState status="auth" /> : null}
          {state === "error" ? <ProtectedRouteState detail={error} status="error" /> : null}

          {state === "ready" && delivery ? (
            <section className="grid gap-5">
              <article className="grid gap-5 rounded-lg border border-border bg-white p-5 shadow-[var(--shadow-card)]">
                <div className="flex flex-wrap items-center gap-2">
                  <strong className="break-all text-base text-foreground">
                    {delivery.destinationUrlRedacted}
                  </strong>
                  <span
                    className={cn(
                      "rounded-full border px-3 py-1 text-xs font-bold",
                      statusTone(delivery.status),
                    )}
                  >
                    {delivery.status}
                  </span>
                </div>
                <dl className="grid gap-4 text-sm md:grid-cols-2">
                  <div className="grid gap-1">
                    <dt className="font-bold text-foreground">Created</dt>
                    <dd className="text-muted-foreground">{formatDate(delivery.createdAt)}</dd>
                  </div>
                  <div className="grid gap-1">
                    <dt className="font-bold text-foreground">Last attempt</dt>
                    <dd className="text-muted-foreground">{formatDate(delivery.lastAttemptAt)}</dd>
                  </div>
                  <div className="grid gap-1">
                    <dt className="font-bold text-foreground">Next attempt</dt>
                    <dd className="text-muted-foreground">{formatDate(delivery.nextAttemptAt)}</dd>
                  </div>
                  <div className="grid gap-1">
                    <dt className="font-bold text-foreground">Response status</dt>
                    <dd className="text-muted-foreground">{delivery.responseStatus ?? "-"}</dd>
                  </div>
                </dl>
                {delivery.errorMessage ? (
                  <div className="grid gap-1">
                    <h2 className="font-bold text-foreground">Error</h2>
                    <pre className="overflow-x-auto rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                      {delivery.errorMessage}
                    </pre>
                  </div>
                ) : null}
                {delivery.responseBody ? (
                  <div className="grid gap-1">
                    <h2 className="font-bold text-foreground">Response body</h2>
                    <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-slate-50 p-3 text-sm text-muted-foreground">
                      {delivery.responseBody}
                    </pre>
                  </div>
                ) : null}
              </article>
              {["failed", "retrying"].includes(delivery.status) ? (
                <Button asChild className="w-fit" variant="outline">
                  <Link href={`/account/events/deliveries/${delivery.id}/replay`}>
                    <RotateCcw className="size-4" />
                    Replay delivery
                  </Link>
                </Button>
              ) : null}
            </section>
          ) : null}

          {state === "error" ? <AlertCircle className="sr-only" /> : null}
        </div>
      </main>
    </>
  );
}
