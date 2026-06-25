"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { PublicHeader } from "@/components/site-header";
import { listCategories } from "@/lib/api/hub";
import type { RegistryCategoryRead } from "@/lib/api/generated/model";

type LoadState = "loading" | "ready" | "error";

function categoryHref(slug: string) {
  return `/categories/${encodeURIComponent(slug)}`;
}

export default function CategoriesPage() {
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [categories, setCategories] = useState<RegistryCategoryRead[]>([]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setState("loading");
      setError("");
      listCategories()
        .then((response) => {
          setCategories(response.categories);
          setState("ready");
        })
        .catch((caught) => {
          setError(caught instanceof Error ? caught.message : "Unable to load categories.");
          setState("error");
        });
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, []);

  return (
    <div className="server-detail-page">
      <PublicHeader />

      <main className="server-detail-main">
        <section className="category-page-header">
          <div>
            <h1>Categories</h1>
            <p>Browse published MCP servers by category.</p>
          </div>
        </section>

        {state === "loading" ? (
          <div className="empty-state">
            <div className="empty-title">Loading</div>
            <div className="empty-detail">Fetching categories.</div>
          </div>
        ) : null}

        {state === "error" ? (
          <div className="empty-state">
            <div className="empty-title">Categories unavailable</div>
            <div className="empty-detail">{error}</div>
          </div>
        ) : null}

        {state === "ready" && categories.length === 0 ? (
          <div className="empty-state">
            <div className="empty-title">No categories</div>
            <div className="empty-detail">No registry categories are available.</div>
          </div>
        ) : null}

        {state === "ready" && categories.length > 0 ? (
          <div className="category-grid">
            {categories.map((category) => (
              <Link className="category-card" href={categoryHref(category.slug)} key={category.id}>
                <strong>{category.name}</strong>
                {category.description ? <span>{category.description}</span> : null}
              </Link>
            ))}
          </div>
        ) : null}
      </main>
    </div>
  );
}
