import type { Metadata } from "next";

import { siteConfig } from "@/lib/site";

import { CategoriesClient } from "./categories-client";

const title = "MCP server categories";
const description = "Browse published Model Context Protocol server definitions by category on Wardn Hub.";

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

export default function CategoriesPage() {
  return <CategoriesClient />;
}
