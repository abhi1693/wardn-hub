import { cookies, headers } from "next/headers";

import type {
  RegistryCategoryListResponse,
  RegistryPublishedServerListResponse,
  RegistryServerDetailResponse,
  RegistryServerListResponse,
  RegistryServerRead,
} from "@/lib/api/generated/model";
import { PUBLIC_CARD_FIELDS } from "@/lib/registry-fields";
import type {
  DetailTab,
  ServerDetailTabResponse,
  ServerSummaryResponse,
} from "@/lib/server-detail-tabs";
import { serverTabApiPath } from "@/lib/server-detail-tabs";
import { resolveSiteUrl } from "@/lib/site";

const API_PREFIX = "/api/v1";
const PAGE_SIZE = 100;
export const SITEMAP_CATALOG_CHUNK_SIZE = 2000;

class RegistryRequestError extends Error {
  status: number;

  constructor(status: number, path: string) {
    super(`Registry API returned ${status} from ${path}`);
    this.name = "RegistryRequestError";
    this.status = status;
  }
}

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

async function registryAuthHeaders() {
  const forwardedHeaders: Record<string, string> = {};

  try {
    const requestCookies = await cookies();
    const cookieHeader = requestCookies.toString();
    if (cookieHeader) {
      forwardedHeaders.Cookie = cookieHeader;
    }
  } catch {
    // Build-time catalog helpers run without an HTTP request, so there are no cookies to forward.
  }

  try {
    const requestHeaders = await headers();
    const authorization = requestHeaders.get("authorization");
    if (authorization) {
      forwardedHeaders.Authorization = authorization;
    }
  } catch {
    // Static generation has no request headers to forward.
  }

  return forwardedHeaders;
}

async function registryRequest<T>(path: string, params?: Record<string, string | number>) {
  const url = new URL(`${resolveApiBaseUrl()}${path}`);
  for (const [key, value] of Object.entries(params ?? {})) {
    url.searchParams.set(key, String(value));
  }
  const authHeaders = await registryAuthHeaders();
  const hasAuthHeaders = Object.keys(authHeaders).length > 0;

  const response = await fetch(url, {
    ...(hasAuthHeaders ? { cache: "no-store" } : { next: { revalidate: 3600 } }),
    headers: { Accept: "application/json", ...authHeaders },
  });

  if (!response.ok) {
    throw new RegistryRequestError(response.status, url.pathname);
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
  namespace?: string;
  namespaceType?: string;
  namespaceVerificationStatus?: string;
  registryType?: string;
  search?: string;
  transportType?: string;
}) {
  const servers: RegistryServerRead[] = [];
  let cursor = "";
  const maxServers = params?.limit ?? SITEMAP_CATALOG_CHUNK_SIZE;

  while (servers.length < maxServers) {
    const response = await registryRequest<RegistryServerListResponse>("/mcp/servers", {
      ...(params?.category ? { category: params.category } : {}),
      fields: PUBLIC_CARD_FIELDS,
      limit: Math.min(PAGE_SIZE, maxServers - servers.length),
      ...(params?.namespace ? { namespace: params.namespace } : {}),
      ...(params?.namespaceType ? { namespaceType: params.namespaceType } : {}),
      ...(params?.namespaceVerificationStatus
        ? { namespaceVerificationStatus: params.namespaceVerificationStatus }
        : {}),
      ...(params?.registryType ? { registry_type: params.registryType } : {}),
      ...(params?.search ? { search: params.search } : {}),
      ...(params?.transportType ? { transport_type: params.transportType } : {}),
      ...(cursor ? { cursor } : {}),
    });

    servers.push(...response.servers.filter((server) => Boolean(server.latestVersion)));
    if (servers.length >= maxServers) return servers.slice(0, maxServers);

    cursor = response.metadata.nextCursor ?? "";
    if (!cursor) break;
  }

  return servers;
}

export async function listPublishedRegistryServerPage(params?: {
  category?: string;
  cursor?: string;
  limit?: number;
  namespace?: string;
  namespaceType?: string;
  namespaceVerificationStatus?: string;
  search?: string;
}) {
  const response = await registryRequest<RegistryServerListResponse>("/mcp/servers", {
    ...(params?.category ? { category: params.category } : {}),
    ...(params?.cursor ? { cursor: params.cursor } : {}),
    ...(params?.namespace ? { namespace: params.namespace } : {}),
    ...(params?.namespaceType ? { namespaceType: params.namespaceType } : {}),
    ...(params?.namespaceVerificationStatus
      ? { namespaceVerificationStatus: params.namespaceVerificationStatus }
      : {}),
    ...(params?.search ? { search: params.search } : {}),
    fields: PUBLIC_CARD_FIELDS,
    limit: params?.limit ?? PAGE_SIZE,
  });

  return {
    nextCursor: response.metadata.nextCursor ?? "",
    servers: response.servers.filter((server) => Boolean(server.latestVersion)),
  };
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

export async function getPublishedRegistryServerTab(serverName: string, tab: DetailTab) {
  try {
    return await registryRequest<ServerDetailTabResponse>(serverTabApiPath(serverName, tab));
  } catch (error) {
    if (!(error instanceof RegistryRequestError) || error.status !== 404) {
      throw error;
    }
    return serverDetailTabFallback(await getPublishedRegistryServer(serverName), tab);
  }
}

export async function getPublishedRegistryServerSummary(serverName: string) {
  return registryRequest<ServerSummaryResponse>(
    `/mcp/servers/${serverName.split("/").map(encodeURIComponent).join("/")}/summary`,
  );
}

export function serverDetailPath(serverName: string) {
  return `/servers/${serverName.split("/").map(encodeURIComponent).join("/")}`;
}

function serverDetailTabFallback(
  detail: RegistryServerDetailResponse,
  tab: DetailTab,
): ServerDetailTabResponse {
  const server = detail.server;
  const baseServer = {
    icons: server.icons,
    id: server.id,
    name: server.name,
    title: server.title,
  };

  if (tab === "schema") {
    return {
      server: baseServer,
      versions: detail.versions?.map((version) => ({
        id: version.id,
        isLatest: version.isLatest,
        packages: version.packages,
        remotes: version.remotes,
        serverJson: version.serverJson,
        title: version.title,
        version: version.version,
      })),
    };
  }

  if (tab === "score") {
    return {
      server: baseServer,
      versions: detail.versions?.map((version) => ({
        id: version.id,
        isLatest: version.isLatest,
        qualityScore: version.qualityScore,
        title: version.title,
        trustReport: version.trustReport,
        version: version.version,
      })),
    };
  }

  return {
    server: {
      ...baseServer,
      categories: server.categories,
      description: server.description,
      repository: server.repository,
      updatedAt: server.updatedAt,
      websiteUrl: server.websiteUrl,
    },
    versions: detail.versions?.map((version) => ({
      description: version.description,
      documentation: version.documentation,
      id: version.id,
      isLatest: version.isLatest,
      partnerSupport: version.partnerSupport,
      publishedAt: version.publishedAt,
      publishedBy: version.publishedBy,
      repository: version.repository,
      title: version.title,
      updatedAt: version.updatedAt,
      version: version.version,
      websiteUrl: version.websiteUrl,
    })),
  };
}
