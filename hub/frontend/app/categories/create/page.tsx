"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { PublicHeader } from "@/components/site-header";
import { createCategory, currentUser, listCategories } from "@/lib/api/hub";

import { CategoryForm } from "../category-form";

type AccessState = "loading" | "allowed" | "denied";

export default function CreateCategoryPage() {
  const router = useRouter();
  const [accessState, setAccessState] = useState<AccessState>("loading");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [initialSortOrder, setInitialSortOrder] = useState(10);

  useEffect(() => {
    currentUser()
      .then((user) => {
        if (!user.is_superuser) {
          setError("Category management requires superuser access.");
          setAccessState("denied");
          return null;
        }
        return listCategories();
      })
      .then((response) => {
        if (!response) return;
        const maxSortOrder = Math.max(0, ...response.categories.map((category) => category.sortOrder));
        setInitialSortOrder(maxSortOrder + 10);
        setAccessState("allowed");
      })
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : "Authentication required.");
        setAccessState("denied");
      });
  }, []);

  return (
    <div className="server-detail-page">
      <PublicHeader />

      <main className="server-detail-main">
        <section className="category-page-header">
          <div>
            <h1>Create Category</h1>
            <p>Add a category for organizing published MCP servers.</p>
          </div>
          <Link className="site-action-link" href="/categories">
            Categories
          </Link>
        </section>

        {accessState === "loading" ? (
          <div className="empty-state">
            <div className="empty-title">Loading</div>
            <div className="empty-detail">Checking category access.</div>
          </div>
        ) : null}

        {accessState === "denied" ? (
          <div className="empty-state">
            <div className="empty-title">Access denied</div>
            <div className="empty-detail">{error}</div>
          </div>
        ) : null}

        {accessState === "allowed" ? (
          <>
            {error ? <div className="error-banner">{error}</div> : null}
            <CategoryForm
              initialValues={{
                slug: "",
                name: "",
                description: "",
                sortOrder: initialSortOrder,
              }}
              isSubmitting={isSubmitting}
              onSubmit={async (values) => {
                setError("");
                setIsSubmitting(true);
                try {
                  await createCategory(values);
                  router.push("/categories");
                } catch (caught) {
                  setError(caught instanceof Error ? caught.message : "Unable to create category.");
                } finally {
                  setIsSubmitting(false);
                }
              }}
              submitLabel="Create Category"
            />
          </>
        ) : null}
      </main>
    </div>
  );
}
