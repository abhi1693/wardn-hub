"use client";

import { Server } from "lucide-react";
import { useEffect, useState } from "react";

import { ServerCard } from "@/components/server-card";
import { PublicHeader } from "@/components/site-header";
import { HubApiError, listPublishedServers } from "@/lib/api/hub";
import type { RegistryServerRead } from "@/lib/api/generated/model";

type LoadState = "idle" | "loading" | "ready" | "error" | "auth";

function statusFromError(error: unknown): LoadState {
  return error instanceof HubApiError && error.status === 401 ? "auth" : "error";
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <div className="empty-title">{title}</div>
      <div className="empty-detail">{detail}</div>
    </div>
  );
}

export default function Home() {
  const [servers, setServers] = useState<RegistryServerRead[]>([]);
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;

    async function refresh() {
      setState("loading");
      setError("");
      try {
        const response = await listPublishedServers({ limit: 60 });
        if (!active) return;
        setServers(response.servers);
        setState("ready");
      } catch (caught) {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "Unable to load registry.");
        setState(statusFromError(caught));
      }
    }

    void refresh();

    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="site-shell">
      <PublicHeader />
      <section className="workspace">
        <div className="home-view simple-home">
          {state === "loading" ? <EmptyState title="Loading" detail="Fetching MCP servers." /> : null}
          {state === "auth" ? (
            <EmptyState title="Authentication required" detail="Registry records are hidden." />
          ) : null}
          {state === "error" ? <EmptyState title="Registry unavailable" detail={error} /> : null}
          {state === "ready" && servers.length === 0 ? (
            <div className="server-grid">
              <article className="server-card empty-server-card">
                <span className="server-card-head">
                  <span className="server-card-icon">
                    <Server size={22} />
                  </span>
                  <span>
                    <strong>No MCP servers published yet</strong>
                    <small>Registry</small>
                  </span>
                </span>
                <span className="server-card-description">
                  Once submissions are approved and published, this page will show one card per MCP
                  server.
                </span>
              </article>
            </div>
          ) : null}
          {servers.length > 0 ? (
            <div className="server-grid">
              {servers.map((server) => (
                <ServerCard key={server.id} server={server} />
              ))}
            </div>
          ) : null}
        </div>
      </section>
    </main>
  );
}
