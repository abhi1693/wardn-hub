"use client";

import Link from "next/link";
import { BellRing, Plus, RefreshCw, Webhook } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ProtectedRouteState } from "@/components/protected-route-state";
import { PublicHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createEventRule, HubApiError, listEventTypes } from "@/lib/api/hub";
import type { EventTypeRead } from "@/lib/api/generated/model";
import { EVENT_RULE_SECRET_STORAGE_KEY, EventTypeCheckbox, LoadState } from "../shared";

function stateFromError(error: unknown): LoadState {
  return error instanceof HubApiError && error.status === 401 ? "auth" : "error";
}

export default function CreateEventRulePage() {
  const router = useRouter();
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [eventTypes, setEventTypes] = useState<EventTypeRead[]>([]);
  const [selectedEventTypes, setSelectedEventTypes] = useState<string[]>([]);
  const [name, setName] = useState("Submission automation");
  const [description, setDescription] = useState("");
  const [url, setUrl] = useState("");
  const [generateSigningSecret, setGenerateSigningSecret] = useState(false);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let active = true;
    listEventTypes()
      .then((response) => {
        if (!active) return;
        setEventTypes(response.eventTypes);
        const defaultEvent = response.eventTypes.find(
          (eventType) => eventType.eventType === "submission.submitted",
        );
        setSelectedEventTypes(defaultEvent ? [defaultEvent.eventType] : []);
        setState("ready");
      })
      .catch((caught) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "Unable to load event types.");
        setState(stateFromError(caught));
      });
    return () => {
      active = false;
    };
  }, []);

  function setEventType(eventType: string, enabled: boolean) {
    if (enabled) {
      setSelectedEventTypes([...new Set([...selectedEventTypes, eventType])]);
      return;
    }
    setSelectedEventTypes(selectedEventTypes.filter((value) => value !== eventType));
  }

  async function submitRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || !url.trim() || selectedEventTypes.length === 0) return;
    setCreating(true);
    setError("");
    try {
      const response = await createEventRule({
        name: name.trim(),
        description: description.trim(),
        eventTypes: selectedEventTypes,
        actionType: "webhook",
        actionConfig: {
          url: url.trim(),
          ...(generateSigningSecret ? { generateSigningSecret: true } : {}),
        },
        conditions: {},
      });
      if (response.signingSecret) {
        window.sessionStorage.setItem(EVENT_RULE_SECRET_STORAGE_KEY, response.signingSecret);
      }
      router.push("/account/events");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create event rule.");
    } finally {
      setCreating(false);
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
        <div className="grid gap-5">
          {state === "ready" ? (
            <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <div className="grid gap-1">
                <h1 className="flex items-center gap-2 text-3xl font-black tracking-normal text-foreground">
                  <BellRing className="size-6 text-muted-foreground" />
                  <span>Create event rule</span>
                </h1>
                <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                  Select one or more events and send them to a webhook.
                </p>
              </div>
            </header>
          ) : null}

          {state === "loading" ? <ProtectedRouteState status="loading" /> : null}
          {state === "auth" ? <ProtectedRouteState status="auth" /> : null}
          {state === "error" ? <ProtectedRouteState detail={error} status="error" /> : null}

          {state === "ready" && error ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
              {error}
            </div>
          ) : null}

          {state === "ready" ? (
            <form
              className="overflow-hidden rounded-lg border border-border bg-white shadow-[var(--shadow-card)]"
              onSubmit={(event) => void submitRule(event)}
            >
              <section className="grid gap-6 p-5">
                <div className="flex items-center gap-2">
                  <span className="inline-flex size-10 items-center justify-center rounded-md bg-slate-100 text-slate-700">
                    <Webhook className="size-5" />
                  </span>
                  <div className="grid gap-1">
                    <h2 className="text-lg font-bold text-foreground">Webhook setup</h2>
                    <p className="text-sm text-muted-foreground">
                      Signing is optional and can be enabled for receivers that verify Wardn headers.
                    </p>
                  </div>
                </div>

                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="grid gap-2">
                    <Label htmlFor="event-rule-name">Name</Label>
                    <Input
                      id="event-rule-name"
                      maxLength={120}
                      onChange={(event) => setName(event.target.value)}
                      required
                      value={name}
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="event-webhook-url">Webhook URL</Label>
                    <Input
                      id="event-webhook-url"
                      onChange={(event) => setUrl(event.target.value)}
                      placeholder="https://automation.example.com/wardn"
                      required
                      type="url"
                      value={url}
                    />
                  </div>
                  <div className="grid gap-2 lg:col-span-2">
                    <Label htmlFor="event-description">Description</Label>
                    <Input
                      id="event-description"
                      maxLength={2000}
                      onChange={(event) => setDescription(event.target.value)}
                      placeholder="Submission review automation"
                      value={description}
                    />
                  </div>
                </div>

                <label className="flex cursor-pointer items-start gap-3 rounded-md border border-border bg-slate-50 p-3">
                  <input
                    checked={generateSigningSecret}
                    className="mt-1 size-4"
                    onChange={(event) => setGenerateSigningSecret(event.target.checked)}
                    type="checkbox"
                  />
                  <span className="grid gap-1">
                    <span className="text-sm font-bold text-foreground">
                      Generate a signing secret
                    </span>
                    <span className="text-sm leading-5 text-muted-foreground">
                      Include Wardn signature headers so the receiver can verify webhook
                      authenticity.
                    </span>
                  </span>
                </label>

                <div className="grid gap-3">
                  <div>
                    <div>
                      <h3 className="font-bold text-foreground">Events</h3>
                      <p className="text-sm text-muted-foreground">
                        Select every event type this rule should receive.
                      </p>
                    </div>
                  </div>
                  <div className="grid gap-1 rounded-lg border border-border p-2 md:grid-cols-2">
                    {eventTypes.map((eventType) => (
                      <EventTypeCheckbox
                        checked={selectedEventTypes.includes(eventType.eventType)}
                        eventType={eventType}
                        key={eventType.eventType}
                        onChange={(enabled) => setEventType(eventType.eventType, enabled)}
                      />
                    ))}
                  </div>
                </div>
              </section>

              <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border bg-slate-50 px-5 py-4">
                <Button asChild type="button" variant="outline">
                  <Link href="/account/events">Cancel</Link>
                </Button>
                <Button
                  disabled={creating || !name.trim() || !url.trim() || selectedEventTypes.length === 0}
                  type="submit"
                >
                  {creating ? <RefreshCw className="size-4" /> : <Plus className="size-4" />}
                  {creating ? "Creating" : "Create rule"}
                </Button>
              </div>
            </form>
          ) : null}
        </div>
      </main>
    </>
  );
}
