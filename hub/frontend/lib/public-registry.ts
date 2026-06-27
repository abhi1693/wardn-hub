import type {
  RegistryCategoryListResponse,
  RegistryPublishedServerListResponse,
  RegistryServerDetailResponse,
  RegistryServerListResponse,
  RegistryServerRead,
} from "@/lib/api/generated/model";
import { resolveSiteUrl } from "@/lib/site";

const API_PREFIX = "/api/v1";
const PAGE_SIZE = 100;
const PUBLIC_CARD_FIELDS = [
  "id",
  "name",
  "title",
  "description",
  "websiteUrl",
  "repository",
  "icons",
  "status",
  "visibility",
  "latestVersion",
  "qualityScore",
  "categories",
  "createdAt",
  "updatedAt",
].join(",");
export const SITEMAP_CATALOG_CHUNK_SIZE = 2000;

function stripTrailingSlash(value: string) {
  return value.replace(/\/+$/, "");
}

function resolveApiBaseUrl() {
  const raw =
    process.env.WARDN_HUB_API_INTERNAL_BASE_URL?.trim() ||
    process.env.NEXT_PUBLIC_API_BASE_URL?.trim() ||
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

async function registryRequest<T>(path: string, params?: Record<string, string | number>) {
  const url = new URL(`${resolveApiBaseUrl()}${path}`);
  for (const [key, value] of Object.entries(params ?? {})) {
    url.searchParams.set(key, String(value));
  }

  const response = await fetch(url, {
    headers: { Accept: "application/json" },
    next: { revalidate: 3600 },
  });

  if (!response.ok) {
    throw new Error(`Registry API returned ${response.status} from ${url.pathname}`);
  }

  return (await response.json()) as T;
}

export async function listPublicCategories() {
  const response = await registryRequest<RegistryCategoryListResponse>("/mcp/categories");
  return response.categories;
}

export async function listPublishedRegistryServers(params?: {
  category?: string;
  limit?: number;
}) {
  const servers: RegistryServerRead[] = [];
  let cursor = "";
  const maxServers = params?.limit ?? SITEMAP_CATALOG_CHUNK_SIZE;

  while (servers.length < maxServers) {
    const response = await registryRequest<RegistryServerListResponse>("/mcp/servers", {
      ...(params?.category ? { category: params.category } : {}),
      fields: PUBLIC_CARD_FIELDS,
      limit: Math.min(PAGE_SIZE, maxServers - servers.length),
      ...(cursor ? { cursor } : {}),
    });

    servers.push(...response.servers.filter((server) => Boolean(server.latestVersion)));
    if (servers.length >= maxServers) return servers.slice(0, maxServers);

    cursor = response.metadata.nextCursor ?? "";
    if (!cursor) break;
  }

  return servers;
}

export async function countPublishedRegistryServers() {
  const response = await registryRequest<RegistryPublishedServerListResponse>("/mcp/catalog", {
    fields: "id",
    page: 1,
  });
  return response.metadata.total;
}

export async function listPublishedRegistryServerSitemapChunk(chunkIndex: number) {
  const servers: RegistryServerRead[] = [];
  const startOffset = chunkIndex * SITEMAP_CATALOG_CHUNK_SIZE;
  let cursor = String(startOffset);

  while (servers.length < SITEMAP_CATALOG_CHUNK_SIZE) {
    const response = await registryRequest<RegistryServerListResponse>("/mcp/servers", {
      cursor,
      fields: PUBLIC_CARD_FIELDS,
      limit: Math.min(PAGE_SIZE, SITEMAP_CATALOG_CHUNK_SIZE - servers.length),
    });

    servers.push(...response.servers.filter((server) => Boolean(server.latestVersion)));

    cursor = response.metadata.nextCursor ?? "";
    if (!cursor) break;
  }

  return servers;
}

export async function getPublishedRegistryServer(serverName: string) {
  const response = await registryRequest<RegistryServerDetailResponse>(
    `/mcp/servers/${serverName.split("/").map(encodeURIComponent).join("/")}`,
  );
  return response;
}

export function serverDetailPath(serverName: string) {
  return `/servers/${serverName.split("/").map(encodeURIComponent).join("/")}`;
}
