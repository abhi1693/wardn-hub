"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { PublicHeader } from "@/components/site-header";
import { currentUser, listCategories, updateCategory } from "@/lib/api/hub";
import type { RegistryCategoryRead } from "@/lib/api/generated/model";

import { CategoryForm } from "../../category-form";

type AccessState = "loading" | "allowed" | "denied";

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
        setAccessState("denied");
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
        <section className="category-page-header">
          <div>
            <h1>Edit Category</h1>
            <p>{category?.name ?? categorySlug}</p>
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

        {accessState === "allowed" && !category ? (
          <div className="empty-state">
            <div className="empty-title">Category unavailable</div>
            <div className="empty-detail">No active category exists for this slug.</div>
          </div>
        ) : null}

        {accessState === "allowed" && category ? (
          <>
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
