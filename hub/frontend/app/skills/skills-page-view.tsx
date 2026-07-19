import { PublicHeader } from "@/components/site-header";
import type { SkillPagination, SkillRead } from "@/lib/api/generated/model";
import { SKILLS_PAGE_SIZE } from "@/lib/public-listing-limits";
import { listPublicSkillsPage, searchPublicSkillsPage } from "@/lib/public-skills";
import { SkillsClient } from "./skills-client";

export type SkillView = "all-time" | "hot" | "trending";
export type SkillAuditFilter = "fail" | "pass" | "unaudited" | "warn";
export type SkillsSearchParams = Promise<{
  audit_status?: string | string[];
  official?: string | string[];
  q?: string | string[];
}>;

function firstSearchParam(value: string | string[] | undefined) {
  if (Array.isArray(value)) return value[0]?.trim() ?? "";
  return value?.trim() ?? "";
}

function emptyPagination(): SkillPagination {
  return { hasMore: false, page: 0, perPage: SKILLS_PAGE_SIZE, total: 0 };
}

function auditFilterParam(value: string | string[] | undefined): SkillAuditFilter | undefined {
  const filter = firstSearchParam(value).toLowerCase();
  if (filter === "pass" || filter === "warn" || filter === "fail" || filter === "unaudited") {
    return filter;
  }
  return undefined;
}

function officialFilterParam(value: string | string[] | undefined): boolean | undefined {
  const filter = firstSearchParam(value).toLowerCase();
  if (filter === "true") return true;
  if (filter === "false") return false;
  return undefined;
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
  const auditStatus = auditFilterParam(resolvedSearchParams?.audit_status);
  const official = officialFilterParam(resolvedSearchParams?.official);
  const state = await (async () => {
    try {
      if (searchQuery.length >= 3) {
        const response = await searchPublicSkillsPage({
          auditStatus,
          limit: SKILLS_PAGE_SIZE,
          official,
          query: searchQuery,
        });
        return {
          auditEnabled: response.auditEnabled,
          error: "",
          pagination: emptyPagination(),
          searchCursor: response.nextCursor,
          skills: response.skills,
        };
      }
      if (searchQuery) {
        const response = await listPublicSkillsPage({ limit: 1 });
        return {
          auditEnabled: response.auditEnabled,
          error: "",
          pagination: emptyPagination(),
          searchCursor: "",
          skills: [] as SkillRead[],
        };
      }
      const response = await listPublicSkillsPage({
        auditStatus,
        limit: SKILLS_PAGE_SIZE,
        official,
        query: searchQuery,
        view,
      });
      return {
        auditEnabled: response.auditEnabled,
        error: "",
        pagination: response.pagination,
        searchCursor: "",
        skills: response.skills,
      };
    } catch (caught) {
      return {
        auditEnabled: false,
        error: caught instanceof Error ? caught.message : "Unable to load skills.",
        pagination: emptyPagination(),
        searchCursor: "",
        skills: [] as SkillRead[],
      };
    }
  })();

  return (
    <main className="site-shell skills-index-page">
      <PublicHeader />
      <SkillsClient
        auditEnabled={state.auditEnabled}
        initialError={state.error}
        initialPagination={state.pagination}
        initialAuditStatus={auditStatus}
        initialOfficial={official}
        initialQuery={searchQuery}
        initialSearchCursor={state.searchCursor}
        initialSkills={state.skills}
        initialView={view}
      />
    </main>
  );
}
