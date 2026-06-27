import type { Metadata } from "next";

import { listPublicCategories } from "@/lib/public-registry";
import { siteConfig } from "@/lib/site";
import { categoryIndexJsonLd, JsonLdScript } from "@/lib/structured-data";

import { CategoriesClient } from "./categories-client";

const title = "MCP server categories";
const description = "Browse community-curated Model Context Protocol servers by category on Wardn Hub.";

export const revalidate = 3600;

export const metadata: Metadata = {
  alternates: {
    canonical: "/categories",
  },
  description,
  openGraph: {
    description,
    title,
    url: "/categories",
  },
  title,
  twitter: {
    card: "summary",
    description,
    title: `${title} | ${siteConfig.name}`,
  },
};

export default async function CategoriesPage() {
  const { categories, error } = await (async () => {
    try {
      return { categories: await listPublicCategories(), error: "" };
    } catch (caught) {
      return {
        categories: [],
        error: caught instanceof Error ? caught.message : "Unable to load categories.",
      };
    }
  })();

  return (
    <>
      <JsonLdScript data={categoryIndexJsonLd(categories)} id="categories-json-ld" />
      <CategoriesClient initialCategories={categories} initialError={error} />
    </>
  );
}
