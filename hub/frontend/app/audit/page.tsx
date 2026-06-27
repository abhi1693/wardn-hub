"use client";

import { AlertCircle, History } from "lucide-react";
import { useEffect, useState } from "react";

import { ProtectedRouteState } from "@/components/protected-route-state";
import { PublicHeader } from "@/components/site-header";
import { HubApiError, listAuditEvents } from "@/lib/api/hub";
import type { AuditEventRead } from "@/lib/api/generated/model";

type LoadState = "loading" | "ready" | "error" | "auth";

function statusFromError(error: unknown): LoadState {
  return error instanceof HubApiError && error.status === 401 ? "auth" : "error";
}

function formatDate(value?: string | null) {
  if (!value) return "";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <div className="empty-title">{title}</div>
      <div className="empty-detail">{detail}</div>
    </div>
  );
}

export default function AuditPage() {
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [events, setEvents] = useState<AuditEventRead[]>([]);

  useEffect(() => {
    let active = true;

    listAuditEvents()
      .then((response) => {
        if (!active) return;
        setEvents(response.events);
        setState("ready");
      })
      .catch((caught) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "Unable to load audit events.");
        setState(statusFromError(caught));
      });

    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="site-shell">
      <PublicHeader />
      <section className="workspace">
        <div className="view">
          {state === "ready" ? (
            <header className="view-header">
              <div>
                <p className="eyebrow">Operations</p>
                <h1>Audit events</h1>
              </div>
              <div className="header-icon">
                <History size={18} />
              </div>
            </header>
          ) : null}
          <div className="table-surface roomy">
            {state === "loading" ? <ProtectedRouteState status="loading" /> : null}
            {state === "auth" ? (
              <ProtectedRouteState status="auth" />
            ) : null}
            {state === "error" ? (
              <EmptyState title="Unable to load audit events" detail={error || "Request failed."} />
            ) : null}
            {state === "ready" && events.length === 0 ? (
              <EmptyState title="No events" detail="Audit stream is empty." />
            ) : null}
            {state === "ready" && events.length > 0 ? (
              <div className="records">
                {events.map((event) => (
                  <div className="record-row" key={event.id}>
                    <div>
                      <strong>{event.eventType}</strong>
                      <small>
                        {event.subjectType} · {event.subjectId}
                      </small>
                    </div>
                    <span>{formatDate(event.createdAt)}</span>
                  </div>
                ))}
              </div>
            ) : null}
            {state === "error" ? <AlertCircle className="sr-only" /> : null}
          </div>
        </div>
      </section>
    </main>
  );
}
