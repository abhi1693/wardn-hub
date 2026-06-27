"use client";

import Link from "next/link";
import { AlertCircle, RefreshCw, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { ProtectedRouteState } from "@/components/protected-route-state";
import { PublicHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { getEventDelivery, HubApiError, replayEventDelivery } from "@/lib/api/hub";
import type { EventDeliveryRead } from "@/lib/api/generated/model";
import { formatDate, LoadState, statusTone } from "../../../shared";
import { cn } from "@/lib/utils";

function stateFromError(error: unknown): LoadState {
  return error instanceof HubApiError && error.status === 401 ? "auth" : "error";
}

export default function ReplayEventDeliveryPage() {
  const params = useParams<{ deliveryId: string }>();
  const router = useRouter();
  const deliveryId = params.deliveryId;
  const [state, setState] = useState<LoadState>("loading");
  const [delivery, setDelivery] = useState<EventDeliveryRead | null>(null);
  const [error, setError] = useState("");
  const [replaying, setReplaying] = useState(false);

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

  async function replayDelivery() {
    if (!delivery) return;
    setReplaying(true);
    setError("");
    try {
      await replayEventDelivery(delivery.id);
      router.push(`/account/events/deliveries/${delivery.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to replay event delivery.");
      setReplaying(false);
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
          {state === "ready" && delivery ? (
            <header className="grid justify-items-center gap-3 text-center">
              <h1 className="flex items-center justify-center gap-2 text-3xl font-black tracking-normal text-foreground">
                <RotateCcw className="size-6 text-muted-foreground" />
                <span>Replay delivery</span>
              </h1>
              <p className="text-sm leading-6 text-muted-foreground">
                Queue this failed delivery for another attempt.
              </p>
            </header>
          ) : null}

          {state === "loading" ? <ProtectedRouteState status="loading" /> : null}
          {state === "auth" ? <ProtectedRouteState status="auth" /> : null}
          {state === "error" ? <ProtectedRouteState detail={error} status="error" /> : null}

          {state === "ready" && delivery ? (
            <section className="grid gap-5 rounded-lg border border-border bg-white p-5 shadow-[var(--shadow-card)]">
              {error ? (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
                  {error}
                </div>
              ) : null}
              <div className="grid gap-3 rounded-lg border border-border bg-slate-50 p-4">
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
                <span className="text-sm text-muted-foreground">
                  Last attempt {formatDate(delivery.lastAttemptAt)}
                </span>
              </div>
              <div className="flex flex-wrap items-center justify-center gap-2">
                <Button
                  disabled={replaying}
                  onClick={() => void replayDelivery()}
                  type="button"
                >
                  {replaying ? <RefreshCw className="size-4" /> : <RotateCcw className="size-4" />}
                  {replaying ? "Replaying" : "Replay delivery"}
                </Button>
                <Button asChild disabled={replaying} type="button" variant="outline">
                  <Link href={`/account/events/deliveries/${delivery.id}`}>Cancel</Link>
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
