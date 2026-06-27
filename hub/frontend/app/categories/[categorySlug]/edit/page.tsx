"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ProtectedRouteState } from "@/components/protected-route-state";
import { PublicHeader } from "@/components/site-header";
import { currentUser, listCategories, updateCategory } from "@/lib/api/hub";
import type { RegistryCategoryRead } from "@/lib/api/generated/model";
import { protectedStateFromError, type ProtectedLoadState } from "@/lib/protected-route";

import { CategoryForm } from "../../category-form";

type AccessState = Exclude<ProtectedLoadState, "ready"> | "allowed";

export default function EditCategoryPage() {
  const params = useParams<{ categorySlug?: string }>();
  const categorySlug = params.categorySlug ?? "";
  const router = useRouter();
  const [accessState, setAccessState] = useState<AccessState>("loading");
  const [error, setError] = useState("");
  const [categories, setCategories] = useState<RegistryCategoryRead[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);

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
        setCategories(response.categories);
        setAccessState("allowed");
      })
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : "Unable to load category.");
        setAccessState(protectedStateFromError(caught));
      });
  }, []);

  const category = useMemo(
    () => categories.find((item) => item.slug === categorySlug),
    [categories, categorySlug],
  );

  return (
    <div className="server-detail-page">
      <PublicHeader />

      <main className="server-detail-main">
        {accessState === "loading" ? <ProtectedRouteState status="loading" /> : null}
        {accessState === "auth" ? <ProtectedRouteState status="auth" /> : null}
        {accessState === "denied" ? <ProtectedRouteState detail={error} status="denied" /> : null}
        {accessState === "error" ? <ProtectedRouteState detail={error} status="error" /> : null}

        {accessState === "allowed" && !category ? (
          <div className="empty-state">
            <div className="empty-title">Category unavailable</div>
            <div className="empty-detail">No active category exists for this slug.</div>
          </div>
        ) : null}

        {accessState === "allowed" && category ? (
          <>
            <section className="category-page-header">
              <div>
                <h1>Edit Category</h1>
                <p>{category.name}</p>
              </div>
              <Link className="site-action-link" href="/categories">
                Categories
              </Link>
            </section>
            {error ? <div className="error-banner">{error}</div> : null}
            <CategoryForm
              initialValues={{
                slug: category.slug,
                name: category.name,
                description: category.description,
                sortOrder: category.sortOrder,
              }}
              isSubmitting={isSubmitting}
              onSubmit={async (values) => {
                setError("");
                setIsSubmitting(true);
                try {
                  await updateCategory(categorySlug, values);
                  router.push("/categories");
                } catch (caught) {
                  setError(caught instanceof Error ? caught.message : "Unable to update category.");
                } finally {
                  setIsSubmitting(false);
                }
              }}
              submitLabel="Save Category"
            />
          </>
        ) : null}
      </main>
    </div>
  );
}
