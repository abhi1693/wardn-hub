"use client";

import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ServerCard } from "@/components/server-card";
import { PublicHeader } from "@/components/site-header";
import { listCategories, listPublishedServers } from "@/lib/api/hub";
import type { RegistryCategoryRead, RegistryServerRead } from "@/lib/api/generated/model";

type LoadState = "loading" | "ready" | "error";

export default function CategoryDetailPage() {
  const params = useParams<{ categorySlug?: string }>();
  const categorySlug = params.categorySlug ?? "";
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [categories, setCategories] = useState<RegistryCategoryRead[]>([]);
  const [servers, setServers] = useState<RegistryServerRead[]>([]);

  useEffect(() => {
    if (!categorySlug) return;

    const timeoutId = window.setTimeout(() => {
      setState("loading");
      setError("");
      Promise.all([
        listCategories(),
        listPublishedServers({ category: categorySlug, limit: 60 }),
      ])
        .then(([categoryResponse, serverResponse]) => {
          setCategories(categoryResponse.categories);
          setServers(serverResponse.servers);
          setState("ready");
        })
        .catch((caught) => {
          setError(caught instanceof Error ? caught.message : "Unable to load category.");
          setState("error");
        });
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, [categorySlug]);

  const category = useMemo(
    () => categories.find((item) => item.slug === categorySlug),
    [categories, categorySlug],
  );
  const categoryName = category?.name ?? categorySlug;

  return (
    <div className="server-detail-page">
      <PublicHeader />

      <main className="server-detail-main">
        <section className="category-page-header">
          <div>
            <h1>{categoryName}</h1>
            {category?.description ? <p>{category.description}</p> : null}
          </div>
        </section>

        {state === "loading" ? (
          <div className="empty-state">
            <div className="empty-title">Loading</div>
            <div className="empty-detail">Fetching MCP servers.</div>
          </div>
        ) : null}

        {state === "error" ? (
          <div className="empty-state">
            <div className="empty-title">Category unavailable</div>
            <div className="empty-detail">{error}</div>
          </div>
        ) : null}

        {state === "ready" && servers.length === 0 ? (
          <div className="empty-state">
            <div className="empty-title">No published servers</div>
            <div className="empty-detail">No published MCP servers are listed in this category.</div>
          </div>
        ) : null}

        {state === "ready" && servers.length > 0 ? (
          <div className="server-grid">
            {servers.map((server) => (
              <ServerCard key={server.id} server={server} />
            ))}
          </div>
        ) : null}
      </main>
    </div>
  );
}
