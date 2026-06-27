"use client";

import Link from "next/link";
import {
  BellRing,
  CheckCircle2,
  CircleDot,
  Pencil,
  Play,
  RotateCcw,
  Trash2,
  Webhook,
  XCircle,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import type { EventDeliveryRead, EventRuleRead, EventTypeRead } from "@/lib/api/generated/model";
import { cn } from "@/lib/utils";

export type LoadState = "loading" | "ready" | "error" | "auth";

export const EVENT_RULE_SECRET_STORAGE_KEY = "wardn_hub_created_event_rule_secret";

export function formatDate(value?: string | null) {
  if (!value) return "Never";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function actionUrl(rule: EventRuleRead) {
  const value = rule.actionConfig.url;
  return typeof value === "string" ? value : "";
}

export function hasSigningSecret(rule: EventRuleRead) {
  return rule.actionConfig.hasSigningSecret === true;
}

export function statusTone(status: string) {
  if (status === "succeeded") return "border-green-200 bg-green-50 text-green-700";
  if (status === "failed") return "border-red-200 bg-red-50 text-red-700";
  if (status === "retrying") return "border-amber-200 bg-amber-50 text-amber-800";
  if (status === "running") return "border-blue-200 bg-blue-50 text-blue-700";
  return "border-zinc-200 bg-zinc-50 text-zinc-700";
}

export function deliveryTitle(delivery: EventDeliveryRead) {
  return delivery.event?.eventType || "Webhook delivery";
}

export function deliverySubject(delivery: EventDeliveryRead) {
  const event = delivery.event;
  if (!event) return delivery.eventRecordId;
  return [event.subjectLabel, event.subjectVersion ? `v${event.subjectVersion}` : ""]
    .filter(Boolean)
    .join(" ");
}

export function EmptyPanel({ detail, title }: { detail: string; title: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-card px-5 py-8 text-center">
      <p className="text-sm font-semibold text-foreground">{title}</p>
      <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
    </div>
  );
}

export function SecretPanel({ secret }: { secret: string }) {
  if (!secret) return null;
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
      <div className="font-semibold">Copy this signing secret now.</div>
      <div className="mt-1 text-amber-800">It will not be shown again.</div>
      <code className="mt-3 block overflow-x-auto rounded-md border border-amber-200 bg-white px-3 py-2 text-xs text-amber-950">
        {secret}
      </code>
    </div>
  );
}

export function EventTypeCheckbox({
  checked,
  eventType,
  onChange,
}: {
  checked: boolean;
  eventType: EventTypeRead;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-md border border-transparent px-2 py-3 transition-colors hover:border-slate-200 hover:bg-slate-50">
      <input
        checked={checked}
        className="mt-1 size-4"
        onChange={(event) => onChange(event.target.checked)}
        type="checkbox"
      />
      <span className="grid gap-1">
        <span className="text-sm font-bold text-foreground">{eventType.label}</span>
        <span className="text-sm leading-5 text-muted-foreground">{eventType.description}</span>
        <span className="text-xs font-semibold text-muted-foreground">{eventType.eventType}</span>
      </span>
    </label>
  );
}

export function RuleCard({ rule }: { rule: EventRuleRead }) {
  return (
    <article className="grid gap-4 rounded-lg border border-border bg-white p-4 shadow-[var(--shadow-card)] lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
      <div className="grid min-w-0 gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="inline-flex size-9 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-700">
            <Webhook className="size-4" />
          </span>
          <Link
            className="min-w-0 overflow-hidden text-ellipsis text-base font-bold text-foreground underline-offset-4 hover:underline"
            href={`/account/events/${rule.id}`}
          >
            {rule.name}
          </Link>
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-bold",
              rule.isEnabled
                ? "border-green-200 bg-green-50 text-green-700"
                : "border-zinc-200 bg-zinc-50 text-zinc-700",
            )}
          >
            {rule.isEnabled ? <CheckCircle2 className="size-3" /> : <XCircle className="size-3" />}
            {rule.isEnabled ? "Enabled" : "Disabled"}
          </span>
        </div>
        <p className="truncate text-sm text-muted-foreground">{actionUrl(rule)}</p>
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
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <span>Last triggered {formatDate(rule.lastTriggeredAt)}</span>
          <span aria-hidden="true">/</span>
          <span>Updated {formatDate(rule.updatedAt)}</span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 lg:justify-end">
        <Button asChild size="sm" variant="outline">
          <Link href={`/account/events/${rule.id}/edit`}>
            <Pencil className="size-4" />
            Edit
          </Link>
        </Button>
        <Button asChild size="sm" variant="outline">
          <Link href={`/account/events/${rule.id}/test`}>
            <Play className="size-4" />
            Test
          </Link>
        </Button>
        {hasSigningSecret(rule) ? (
          <Button asChild size="sm" variant="outline">
            <Link href={`/account/events/${rule.id}/rotate-secret`}>
              <RotateCcw className="size-4" />
              Rotate
            </Link>
          </Button>
        ) : (
          <Button disabled size="sm" type="button" variant="outline">
            <RotateCcw className="size-4" />
            Rotate
          </Button>
        )}
        <Button asChild size="sm" variant="destructive">
          <Link href={`/account/events/${rule.id}/delete`}>
            <Trash2 className="size-4" />
            Delete
          </Link>
        </Button>
      </div>
    </article>
  );
}

export function DeliveryCard({ delivery }: { delivery: EventDeliveryRead }) {
  return (
    <article className="group relative grid gap-4 rounded-lg border border-border bg-white p-4 shadow-[var(--shadow-card)] transition-colors hover:border-slate-300 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
      <Link
        aria-label={`Open delivery ${delivery.id}`}
        className="absolute inset-0 z-10 rounded-lg"
        href={`/account/events/deliveries/${delivery.id}`}
      />
      <div className="grid min-w-0 gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="inline-flex size-9 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-700">
            <BellRing className="size-4" />
          </span>
          <strong className="min-w-0 overflow-hidden text-ellipsis text-base text-foreground underline-offset-4 group-hover:underline">
            {deliveryTitle(delivery)}
          </strong>
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-bold",
              statusTone(delivery.status),
            )}
          >
            <CircleDot className="size-3" />
            {delivery.status}
          </span>
        </div>
        <p className="truncate text-sm font-medium text-slate-700">{deliverySubject(delivery)}</p>
        <p className="truncate text-sm text-muted-foreground">{delivery.destinationUrlRedacted}</p>
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <span>Created {formatDate(delivery.createdAt)}</span>
          <span aria-hidden="true">/</span>
          <span>{delivery.attemptCount} attempts</span>
          <span aria-hidden="true">/</span>
          <span>HTTP {delivery.responseStatus ?? "-"}</span>
        </div>
        {delivery.errorMessage ? (
          <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            {delivery.errorMessage}
          </p>
        ) : null}
      </div>
      <div className="relative z-20 flex flex-wrap items-center gap-2 lg:justify-end">
        {["failed", "retrying"].includes(delivery.status) ? (
          <Button asChild size="sm" variant="outline">
            <Link href={`/account/events/deliveries/${delivery.id}/replay`}>
              <RotateCcw className="size-4" />
              Replay
            </Link>
          </Button>
        ) : null}
      </div>
    </article>
  );
}
