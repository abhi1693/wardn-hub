import type { Metadata } from "next";

import { PublicHeader } from "@/components/site-header";
import type { SkillPagination, SkillRead } from "@/lib/api/generated/model";
import { listPublicSkillsPage } from "@/lib/public-skills";
import { SkillsClient } from "./skills-client";

export const revalidate = 60;
const SKILLS_PAGE_SIZE = 60;

type SkillsPageProps = {
  searchParams?: Promise<{
    q?: string | string[];
    view?: string | string[];
  }>;
};

type SkillView = "all-time" | "hot" | "trending";

export const metadata: Metadata = {
  alternates: {
    canonical: "/skills",
  },
  description: "Browse reusable agent skills imported into Wardn Hub.",
  title: "Skills",
};

function emptyPagination(): SkillPagination {
  return { hasMore: false, page: 0, perPage: SKILLS_PAGE_SIZE, total: 0 };
}

function firstSearchParam(value: string | string[] | undefined) {
  if (Array.isArray(value)) return value[0]?.trim() ?? "";
  return value?.trim() ?? "";
}

function skillView(value: string | string[] | undefined): SkillView {
  const candidate = firstSearchParam(value);
  if (candidate === "hot" || candidate === "trending") return candidate;
  return "all-time";
}

export default async function SkillsPage({ searchParams }: SkillsPageProps) {
  const resolvedSearchParams = await searchParams;
  const searchQuery = firstSearchParam(resolvedSearchParams?.q);
  const view = skillView(resolvedSearchParams?.view);
  const state = await (async () => {
    try {
      const response = await listPublicSkillsPage({
        limit: SKILLS_PAGE_SIZE,
        query: searchQuery,
        view,
      });
      return { error: "", pagination: response.pagination, skills: response.skills };
    } catch (caught) {
      return {
        error: caught instanceof Error ? caught.message : "Unable to load skills.",
        pagination: emptyPagination(),
        skills: [] as SkillRead[],
      };
    }
  })();

  return (
    <main className="site-shell">
      <PublicHeader />
      <SkillsClient
        initialError={state.error}
        initialPagination={state.pagination}
        initialQuery={searchQuery}
        initialSkills={state.skills}
        initialView={view}
      />
    </main>
  );
}
