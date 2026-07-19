import type {
  SkillAuditResponse,
  SkillDetailResponse,
  SkillFileRead,
  SkillGitHubImportResponse,
  SkillListResponse,
  SkillPagination,
  SkillRead,
  SkillSearchResponse,
} from "@/lib/api/generated/model";
import { resolveSiteUrl } from "@/lib/site";

const API_PREFIX = "/api/v1";
const DEFAULT_SKILLS_LIMIT = 100;

class SkillsRequestError extends Error {
  status: number;

  constructor(status: number, path: string, detail?: string) {
    super(detail || `Skills API returned ${status} from ${path}`);
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
  return skillsJsonRequest<T>(path, { params });
}

async function skillsJsonRequest<T>(
  path: string,
  options?: {
    body?: unknown;
    method?: "GET" | "POST";
    params?: Record<string, boolean | number | string>;
  },
) {
  const baseUrl = resolveApiBaseUrl();
  const origin = typeof window !== "undefined" ? window.location.origin : resolveSiteUrl();
  const url = new URL(`${baseUrl}${path}`, origin);
  for (const [key, value] of Object.entries(options?.params ?? {})) {
    url.searchParams.set(key, String(value));
  }

  const response = await fetch(url, {
    body: options?.body === undefined ? undefined : JSON.stringify(options.body),
    cache: "no-store",
    headers: {
      Accept: "application/json",
      ...(options?.body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    method: options?.method ?? "GET",
  });

  if (!response.ok) {
    let detail = "";
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      detail = "";
    }
    throw new SkillsRequestError(response.status, url.pathname, detail);
  }

  return (await response.json()) as T;
}

export function skillDetailPath(skillId: string) {
  return `/skills/${skillId.split("/").map(encodeURIComponent).join("/")}`;
}

export function skillFilePathSegments(segments: string[]) {
  if (
    !segments.length ||
    segments.some(
      (segment) =>
        !segment ||
        segment === "." ||
        segment === ".." ||
        segment.includes("/") ||
        segment.includes("\\") ||
        Array.from(segment).some((character) => {
          const codePoint = character.codePointAt(0) ?? 0;
          return codePoint < 32 || codePoint === 127;
        }),
    )
  ) {
    return null;
  }
  return segments.join("/");
}

export function skillFilePath(skillId: string, filePath: string) {
  const normalizedPath = skillFilePathSegments(filePath.split("/"));
  if (!normalizedPath || normalizedPath !== filePath) return null;
  if (filePath === "SKILL.md") return skillDetailPath(skillId);
  return `${skillDetailPath(skillId)}/files/${filePath
    .split("/")
    .map(encodeURIComponent)
    .join("/")}`;
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
  auditStatus?: "fail" | "pass" | "unaudited" | "warn";
  limit?: number;
  official?: boolean;
  owner?: string;
  page?: number;
  query?: string;
  source?: string;
  view?: "all-time" | "hot" | "trending";
}): Promise<{ auditEnabled: boolean; pagination: SkillPagination; skills: SkillRead[] }> {
  const query = params?.query?.trim();
  const listParams: Record<string, boolean | number | string> = {
    page: params?.page ?? 0,
    per_page: params?.limit ?? DEFAULT_SKILLS_LIMIT,
    view: params?.view ?? "all-time",
  };
  if (params?.auditStatus) listParams.audit_status = params.auditStatus;
  if (query) listParams.q = query;
  if (params?.owner) listParams.owner = params.owner;
  if (params?.source) listParams.source = params.source;
  if (params?.official !== undefined) listParams.official = params.official;

  const response = await skillsRequest<SkillListResponse>("/skills", listParams);
  return {
    auditEnabled: response.auditEnabled,
    pagination: response.pagination,
    skills: response.data,
  };
}

export async function searchPublicSkillsPage(params: {
  auditStatus?: "fail" | "pass" | "unaudited" | "warn";
  cursor?: string;
  limit?: number;
  official?: boolean;
  owner?: string;
  query: string;
}): Promise<{
  auditEnabled: boolean;
  hasMore: boolean;
  nextCursor: string;
  skills: SkillRead[];
}> {
  const query = params.query.trim();
  if (query.length < 3) {
    throw new Error("Search queries must contain at least 3 characters.");
  }
  const searchParams: Record<string, boolean | number | string> = {
    limit: params.limit ?? DEFAULT_SKILLS_LIMIT,
    q: query,
  };
  if (params.auditStatus) searchParams.audit_status = params.auditStatus;
  if (params.cursor) searchParams.cursor = params.cursor;
  if (params.official !== undefined) searchParams.official = params.official;
  if (params.owner) searchParams.owner = params.owner;

  const response = await skillsRequest<SkillSearchResponse>("/skills/search", searchParams);
  return {
    auditEnabled: response.auditEnabled,
    hasMore: response.hasMore === true,
    nextCursor: response.nextCursor ?? "",
    skills: response.data,
  };
}

export async function importPublicGitHubSkill(repositoryUrl: string) {
  return skillsJsonRequest<SkillGitHubImportResponse>("/skills/import-github", {
    body: { repositoryUrl },
    method: "POST",
  });
}

export async function getPublicSkill(
  skillId: string,
  options?: { includeBundle?: boolean },
) {
  return skillsRequest<SkillDetailResponse>(
    `/skills/${skillId.split("/").map(encodeURIComponent).join("/")}`,
    options?.includeBundle ? { include_bundle: true } : undefined,
  );
}

export async function getPublicSkillAudit(skillId: string) {
  try {
    return await skillsRequest<SkillAuditResponse>(
      `/skills/audit/${skillId.split("/").map(encodeURIComponent).join("/")}`,
    );
  } catch (error) {
    if (isSkillsNotFoundError(error)) return null;
    throw error;
  }
}

export function publishedSkillFiles(skill: SkillDetailResponse) {
  return (skill.files ?? []).filter(
    (file): file is SkillFileRead => skillFilePath(skill.id, file.path) !== null,
  );
}

export function stripMarkdownFrontmatter(markdown: string) {
  return markdown.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "").trimStart();
}

export function displaySkillName(skill: SkillRead | SkillDetailResponse) {
  if ("name" in skill && skill.name) return skill.name;
  return skill.slug;
}
