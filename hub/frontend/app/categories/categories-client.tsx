"use client";

import Link from "next/link";
import { Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { PublicHeader } from "@/components/site-header";
import { currentUser, deleteCategory, HubApiError, listCategories } from "@/lib/api/hub";
import type { RegistryCategoryRead, UserRead } from "@/lib/api/generated/model";

type LoadState = "ready" | "error";

function categoryHref(slug: string) {
  return `/categories/${encodeURIComponent(slug)}`;
}

function categoryEditHref(slug: string) {
  return `/categories/${encodeURIComponent(slug)}/edit`;
}

export function CategoriesClient({
  initialCategories = [],
  initialError = "",
}: {
  initialCategories?: RegistryCategoryRead[];
  initialError?: string;
}) {
  const [state, setState] = useState<LoadState>(initialError ? "error" : "ready");
  const [error, setError] = useState(initialError);
  const [notice, setNotice] = useState("");
  const [categories, setCategories] = useState<RegistryCategoryRead[]>(initialCategories);
  const [user, setUser] = useState<UserRead | null>(null);
  const [deletingSlug, setDeletingSlug] = useState("");
  const [query, setQuery] = useState("");

  const canManageCategories = Boolean(user?.is_superuser);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filteredCategories = useMemo(() => {
    if (!normalizedQuery) return categories;
    return categories.filter((category) =>
      [category.name, category.description, category.slug]
        .filter(Boolean)
        .some((value) => value?.toLocaleLowerCase().includes(normalizedQuery)),
    );
  }, [categories, normalizedQuery]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setError("");
      currentUser()
        .then((currentAccount) => {
          setUser(currentAccount);
          return listCategories();
        })
        .catch((caught) => {
          if (caught instanceof HubApiError && caught.status === 401) {
            setUser(null);
            return listCategories();
          }
          throw caught;
        })
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

  async function removeCategory(category: RegistryCategoryRead) {
    const confirmed = window.confirm(
      `Delete ${category.name}? Servers currently using it will no longer show this category.`,
    );
    if (!confirmed) return;

    setDeletingSlug(category.slug);
    setError("");
    setNotice("");
    try {
      await deleteCategory(category.slug);
      setCategories((current) => current.filter((item) => item.id !== category.id));
      setNotice(`Deleted ${category.name}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to delete category.");
    } finally {
      setDeletingSlug("");
    }
  }

  return (
    <div className="server-detail-page">
      <PublicHeader />

      <main className="server-detail-main">
        <section className="category-page-header">
          <div>
            <h1>Categories</h1>
            <p>Browse published MCP servers by category.</p>
          </div>
          {canManageCategories ? (
            <Link className="site-nav-cta" href="/categories/create">
              <Plus size={16} />
              Create Category
            </Link>
          ) : null}
        </section>

        {state === "ready" && categories.length > 0 ? (
          <div className="category-directory-toolbar">
            <label className="category-directory-search">
              <Search aria-hidden="true" size={19} />
              <span className="sr-only">Search categories</span>
              <input
                autoComplete="off"
                onChange={(event) => setQuery(event.currentTarget.value)}
                placeholder="Search categories"
                type="search"
                value={query}
              />
              {query ? (
                <button
                  aria-label="Clear category search"
                  onClick={() => setQuery("")}
                  type="button"
                >
                  <X aria-hidden="true" size={17} />
                </button>
              ) : null}
            </label>
            <span aria-live="polite" className="category-directory-count">
              {filteredCategories.length.toLocaleString("en-US")} of{" "}
              {categories.length.toLocaleString("en-US")}
            </span>
          </div>
        ) : null}

        {notice ? <div className="notice">{notice}</div> : null}
        {state === "ready" && error ? <div className="error-banner">{error}</div> : null}

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

        {state === "ready" && filteredCategories.length > 0 ? (
          <div className="category-grid">
            {filteredCategories.map((category) => (
              <article className="category-card" key={category.id}>
                <Link className="category-card-main" href={categoryHref(category.slug)}>
                  <strong>{category.name}</strong>
                  {category.description ? <span>{category.description}</span> : null}
                </Link>
                {canManageCategories ? (
                  <div className="category-card-actions">
                    <Link
                      aria-label={`Edit ${category.name}`}
                      className="icon-button"
                      href={categoryEditHref(category.slug)}
                      title="Edit category"
                    >
                      <Pencil size={16} />
                    </Link>
                    <button
                      aria-label={`Delete ${category.name}`}
                      className="icon-button danger"
                      disabled={deletingSlug === category.slug}
                      onClick={() => void removeCategory(category)}
                      title="Delete category"
                      type="button"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        ) : null}

        {state === "ready" && categories.length > 0 && filteredCategories.length === 0 ? (
          <div className="empty-state">
            <div className="empty-title">No matching categories</div>
            <div className="empty-detail">Try a broader name or capability.</div>
          </div>
        ) : null}
      </main>
    </div>
  );
}
