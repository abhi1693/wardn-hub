"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ProtectedRouteState } from "@/components/protected-route-state";
import { PublicHeader } from "@/components/site-header";
import { createCategory, currentUser, listCategories } from "@/lib/api/hub";
import { protectedStateFromError, type ProtectedLoadState } from "@/lib/protected-route";

import { CategoryForm } from "../category-form";

type AccessState = Exclude<ProtectedLoadState, "ready"> | "allowed";

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
        setAccessState(protectedStateFromError(caught));
      });
  }, []);

  return (
    <div className="server-detail-page">
      <PublicHeader />

      <main className="server-detail-main">
        {accessState === "loading" ? <ProtectedRouteState status="loading" /> : null}
        {accessState === "auth" ? <ProtectedRouteState status="auth" /> : null}
        {accessState === "denied" ? <ProtectedRouteState detail={error} status="denied" /> : null}
        {accessState === "error" ? <ProtectedRouteState detail={error} status="error" /> : null}

        {accessState === "allowed" ? (
          <>
            <section className="category-page-header">
              <div>
                <h1>Create Category</h1>
                <p>Add a category for organizing published MCP servers.</p>
              </div>
              <Link className="site-action-link" href="/categories">
                Categories
              </Link>
            </section>
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
