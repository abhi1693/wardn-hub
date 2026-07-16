import { PublicHeader } from "@/components/site-header";
import type { SkillPagination, SkillRead } from "@/lib/api/generated/model";
import { SKILLS_PAGE_SIZE } from "@/lib/public-listing-limits";
import { listPublicSkillsPage } from "@/lib/public-skills";
import { SkillsClient } from "./skills-client";

export type SkillView = "all-time" | "hot" | "trending";
export type SkillsSearchParams = Promise<{
  q?: string | string[];
}>;

function firstSearchParam(value: string | string[] | undefined) {
  if (Array.isArray(value)) return value[0]?.trim() ?? "";
  return value?.trim() ?? "";
}

function emptyPagination(): SkillPagination {
  return { hasMore: false, page: 0, perPage: SKILLS_PAGE_SIZE, total: 0 };
}

export async function SkillsPageView({
  searchParams,
  view,
}: {
  searchParams?: SkillsSearchParams;
  view: SkillView;
}) {
  const resolvedSearchParams = await searchParams;
  const searchQuery = firstSearchParam(resolvedSearchParams?.q);
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
