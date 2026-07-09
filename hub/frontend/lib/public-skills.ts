import type {
  SkillDetailResponse,
  SkillListResponse,
  SkillPagination,
  SkillRead,
} from "@/lib/api/generated/model";
import { resolveSiteUrl } from "@/lib/site";

const API_PREFIX = "/api/v1";
const DEFAULT_SKILLS_LIMIT = 100;

class SkillsRequestError extends Error {
  status: number;

  constructor(status: number, path: string) {
    super(`Skills API returned ${status} from ${path}`);
    this.name = "SkillsRequestError";
    this.status = status;
  }
}

export function isSkillsNotFoundError(error: unknown) {
  return error instanceof SkillsRequestError && error.status === 404;
}

function stripTrailingSlash(value: string) {
  return value.replace(/\/+$/, "");
}

function resolveApiBaseUrl() {
  const publicApiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (typeof window !== "undefined") {
    return stripTrailingSlash(publicApiBaseUrl || API_PREFIX);
  }

  const raw =
    process.env.WARDN_HUB_API_INTERNAL_BASE_URL?.trim() ||
    publicApiBaseUrl ||
    "http://localhost:8000";
  const base = raw.startsWith("http") ? raw : new URL(raw, resolveSiteUrl()).toString();
  const url = new URL(base);
  const pathname = stripTrailingSlash(url.pathname);

  if (!pathname || pathname === "/") {
    url.pathname = API_PREFIX;
  } else if (pathname === "/api") {
    url.pathname = API_PREFIX;
  } else if (!pathname.endsWith(API_PREFIX)) {
    url.pathname = `${pathname}${API_PREFIX}`;
  }

  url.search = "";
  url.hash = "";
  return stripTrailingSlash(url.toString());
}

async function skillsRequest<T>(path: string, params?: Record<string, boolean | number | string>) {
  const baseUrl = resolveApiBaseUrl();
  const origin = typeof window !== "undefined" ? window.location.origin : resolveSiteUrl();
  const url = new URL(`${baseUrl}${path}`, origin);
  for (const [key, value] of Object.entries(params ?? {})) {
    url.searchParams.set(key, String(value));
  }

  const response = await fetch(url, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw new SkillsRequestError(response.status, url.pathname);
  }

  return (await response.json()) as T;
}

export function skillDetailPath(skillId: string) {
  return `/skills/${skillId.split("/").map(encodeURIComponent).join("/")}`;
}

export function skillOwner(source: string) {
  return source.split("/", 1)[0] || source;
}

export function skillRepo(source: string) {
  return source.split("/")[1] || source;
}

export function skillOwnerPath(owner: string) {
  return `/skills/${encodeURIComponent(owner)}`;
}

export function skillSourcePath(source: string) {
  return `/skills/${source.split("/").map(encodeURIComponent).join("/")}`;
}

export type SkillSourceGroup = {
  isOfficial: boolean;
  owner: string;
  repo: string;
  skills: SkillRead[];
  source: string;
  sourceOwnerIconUrl?: string | null;
  sourceOwnerUrl?: string | null;
  sourceUrl?: string | null;
};

export function groupSkillsBySource(skills: SkillRead[]) {
  const groups = new Map<string, SkillSourceGroup>();

  for (const skill of skills) {
    const existing =
      groups.get(skill.source) ??
      ({
        isOfficial: false,
        owner: skill.sourceOwner || skillOwner(skill.source),
        repo: skill.sourceName || skillRepo(skill.source),
        skills: [],
        source: skill.source,
        sourceOwnerIconUrl: skill.sourceOwnerIconUrl,
        sourceOwnerUrl: skill.sourceOwnerUrl,
        sourceUrl: skill.sourceUrl,
      } satisfies SkillSourceGroup);
    existing.isOfficial = existing.isOfficial || skill.isOfficial === true;
    existing.skills.push(skill);
    groups.set(skill.source, existing);
  }

  return Array.from(groups.values()).sort((left, right) =>
    left.source.localeCompare(right.source),
  );
}

export type SkillOwnerGroup = {
  isOfficial: boolean;
  owner: string;
  sources: SkillSourceGroup[];
  skills: SkillRead[];
};

export function groupSkillsByOwner(skills: SkillRead[]) {
  const sourceGroups = groupSkillsBySource(skills);
  const groups = new Map<string, SkillOwnerGroup>();

  for (const source of sourceGroups) {
    const existing =
      groups.get(source.owner) ??
      ({
        isOfficial: false,
        owner: source.owner,
        sources: [],
        skills: [],
      } satisfies SkillOwnerGroup);
    existing.isOfficial = existing.isOfficial || source.isOfficial;
    existing.sources.push(source);
    existing.skills.push(...source.skills);
    groups.set(source.owner, existing);
  }

  return Array.from(groups.values()).sort((left, right) =>
    left.owner.localeCompare(right.owner),
  );
}

export async function listPublicSkills(params?: {
  limit?: number;
  official?: boolean;
  owner?: string;
  page?: number;
  query?: string;
  source?: string;
  view?: "all-time" | "hot" | "trending";
}) {
  const response = await listPublicSkillsPage(params);
  return response.skills;
}

export async function listPublicSkillsPage(params?: {
  limit?: number;
  official?: boolean;
  owner?: string;
  page?: number;
  query?: string;
  source?: string;
  view?: "all-time" | "hot" | "trending";
}): Promise<{ pagination: SkillPagination; skills: SkillRead[] }> {
  const query = params?.query?.trim();
  const listParams: Record<string, boolean | number | string> = {
    page: params?.page ?? 0,
    per_page: params?.limit ?? DEFAULT_SKILLS_LIMIT,
    view: params?.view ?? "all-time",
  };
  if (query) listParams.q = query;
  if (params?.owner) listParams.owner = params.owner;
  if (params?.source) listParams.source = params.source;
  if (params?.official !== undefined) listParams.official = params.official;

  const response = await skillsRequest<SkillListResponse>("/skills", listParams);
  return { pagination: response.pagination, skills: response.data };
}

export async function getPublicSkill(skillId: string) {
  return skillsRequest<SkillDetailResponse>(
    `/skills/${skillId.split("/").map(encodeURIComponent).join("/")}`,
  );
}

export function findSkillMd(skill: SkillDetailResponse) {
  return skill.files?.find((file) => file.path === "SKILL.md")?.contents ?? "";
}

export function stripMarkdownFrontmatter(markdown: string) {
  return markdown.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "").trimStart();
}

export function displaySkillName(skill: SkillRead | SkillDetailResponse) {
  if ("name" in skill && skill.name) return skill.name;
  return skill.slug;
}
