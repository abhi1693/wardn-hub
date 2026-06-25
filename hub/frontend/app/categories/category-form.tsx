"use client";

import type { FormEvent } from "react";
import { useState } from "react";

import type { RegistryCategoryCreate } from "@/lib/api/generated/model";

type CategoryFormValues = RegistryCategoryCreate;

type CategoryFormProps = {
  initialValues?: CategoryFormValues;
  isSubmitting: boolean;
  submitLabel: string;
  onSubmit: (values: CategoryFormValues) => void | Promise<void>;
};

function slugFromName(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function CategoryForm({
  initialValues,
  isSubmitting,
  submitLabel,
  onSubmit,
}: CategoryFormProps) {
  const [name, setName] = useState(initialValues?.name ?? "");
  const [slug, setSlug] = useState(initialValues?.slug ?? "");
  const [description, setDescription] = useState(initialValues?.description ?? "");
  const [sortOrder, setSortOrder] = useState(String(initialValues?.sortOrder ?? 1000));
  const [slugEdited, setSlugEdited] = useState(Boolean(initialValues?.slug));

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSubmit({
      slug: slugFromName(slug || name),
      name: name.trim(),
      description: description.trim(),
      sortOrder: Number.parseInt(sortOrder, 10) || 1000,
    });
  }

  return (
    <form className="category-form" onSubmit={(event) => void handleSubmit(event)}>
      <div className="category-form-grid">
        <label>
          <span>Name</span>
          <input
            onChange={(event) => {
              const nextName = event.target.value;
              setName(nextName);
              if (!slugEdited) setSlug(slugFromName(nextName));
            }}
            required
            value={name}
          />
        </label>
        <label>
          <span>Slug</span>
          <input
            onChange={(event) => {
              setSlugEdited(true);
              setSlug(slugFromName(event.target.value));
            }}
            pattern="[a-z0-9]+(-[a-z0-9]+)*"
            required
            value={slug}
          />
        </label>
        <label>
          <span>Sort order</span>
          <input
            min={0}
            onChange={(event) => setSortOrder(event.target.value)}
            type="number"
            value={sortOrder}
          />
        </label>
      </div>

      <label>
        <span>Description</span>
        <textarea
          onChange={(event) => setDescription(event.target.value)}
          rows={5}
          value={description}
        />
      </label>

      <div className="category-form-actions">
        <button className="site-nav-cta" disabled={isSubmitting} type="submit">
          {isSubmitting ? "Saving" : submitLabel}
        </button>
      </div>
    </form>
  );
}
