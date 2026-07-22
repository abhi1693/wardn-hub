import type {
  RegistryCategoryListResponse,
  RegistryPublishedServerListResponse,
  RegistryServerDetailResponse,
  RegistryServerListResponse,
  RegistryServerRead,
  RegistryStatsResponse,
} from "@/lib/api/generated/model";
import { PUBLIC_CARD_FIELDS } from "@/lib/registry-fields";
import {
  mergePublishedServers,
  publishedRegistryServerPage,
} from "@/lib/published-registry-page";
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

export function isRegistryNotFoundError(error: unknown) {
  return error instanceof RegistryRequestError && error.status === 404;
}

function stripTrailingSlash(value: string) {
  return value.replace(/\/+$/, "");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => isRecord(item))
    : [];
}

function toolCandidateLists(value: unknown): Record<string, unknown>[][] {
  if (Array.isArray(value)) return [records(value)];
  if (!isRecord(value)) return [];
  if (isRecord(value.result)) {
    const nested = toolCandidateLists(value.result);
    if (nested.length > 0) return nested;
  }
  if (Array.isArray(value.tools)) return [records(value.tools)];
  return [];
}

function promptCandidateLists(value: unknown): Record<string, unknown>[][] {
  if (Array.isArray(value)) return [records(value)];
  if (!isRecord(value)) return [];
  if (isRecord(value.result)) {
    const nested = promptCandidateLists(value.result);
    if (nested.length > 0) return nested;
  }
  if (Array.isArray(value.prompts)) return [records(value.prompts)];
  return [];
}

function resourceCandidateLists(value: unknown): Record<string, unknown>[][] {
  if (Array.isArray(value)) return [records(value)];
  if (!isRecord(value)) return [];
  if (isRecord(value.result)) {
    const nested = resourceCandidateLists(value.result);
    if (nested.length > 0) return nested;
  }
  if (Array.isArray(value.resources)) return [records(value.resources)];
  return [];
}

function resourceTemplateCandidateLists(value: unknown): Record<string, unknown>[][] {
  if (Array.isArray(value)) return [records(value)];
  if (!isRecord(value)) return [];
  if (isRecord(value.result)) {
    const nested = resourceTemplateCandidateLists(value.result);
    if (nested.length > 0) return nested;
  }
  if (Array.isArray(value.resourceTemplates)) return [records(value.resourceTemplates)];
  return [];
}

function toolsFromServerJson(serverJson: unknown) {
  if (!isRecord(serverJson)) return [];
  const meta = isRecord(serverJson._meta) ? serverJson._meta : {};
  const capabilities = isRecord(serverJson.capabilities) ? serverJson.capabilities : {};
  const introspection = isRecord(serverJson.introspection) ? serverJson.introspection : {};
  const mcp = isRecord(serverJson.mcp) ? serverJson.mcp : {};
  const metaCapabilities = isRecord(meta.capabilities) ? meta.capabilities : {};
  const metaIntrospection = isRecord(meta.introspection) ? meta.introspection : {};
  const metaMcp = isRecord(meta.mcp) ? meta.mcp : {};
  const candidates = [
    serverJson.tools,
    serverJson.toolDefinitions,
    serverJson.mcpTools,
    capabilities.tools,
    introspection.tools,
    introspection["tools/list"],
    serverJson["tools/list"],
    mcp.tools,
    mcp["tools/list"],
    meta.tools,
    metaCapabilities.tools,
    metaIntrospection.tools,
    metaIntrospection["tools/list"],
    metaMcp.tools,
    metaMcp["tools/list"],
  ];
  const seen = new Set<string>();
  return candidates
    .flatMap(toolCandidateLists)
    .flat()
    .filter((tool) => {
      const name = typeof tool.name === "string" ? tool.name.trim() : "";
      if (!name || seen.has(name)) return false;
      seen.add(name);
      return true;
    });
}

function promptsFromServerJson(serverJson: unknown) {
  if (!isRecord(serverJson)) return [];
  const meta = isRecord(serverJson._meta) ? serverJson._meta : {};
  const capabilities = isRecord(serverJson.capabilities) ? serverJson.capabilities : {};
  const introspection = isRecord(serverJson.introspection) ? serverJson.introspection : {};
  const mcp = isRecord(serverJson.mcp) ? serverJson.mcp : {};
  const metaCapabilities = isRecord(meta.capabilities) ? meta.capabilities : {};
  const metaIntrospection = isRecord(meta.introspection) ? meta.introspection : {};
  const metaMcp = isRecord(meta.mcp) ? meta.mcp : {};
  const candidates = [
    serverJson.prompts,
    serverJson.promptDefinitions,
    serverJson.mcpPrompts,
    capabilities.prompts,
    introspection.prompts,
    introspection["prompts/list"],
    serverJson["prompts/list"],
    mcp.prompts,
    mcp["prompts/list"],
    meta.prompts,
    metaCapabilities.prompts,
    metaIntrospection.prompts,
    metaIntrospection["prompts/list"],
    metaMcp.prompts,
    metaMcp["prompts/list"],
  ];
  const seen = new Set<string>();
  return candidates
    .flatMap(promptCandidateLists)
    .flat()
    .filter((prompt) => {
      const name = typeof prompt.name === "string" ? prompt.name.trim() : "";
      if (!name || seen.has(name)) return false;
      seen.add(name);
      return true;
    });
}

function resourcesFromServerJson(serverJson: unknown) {
  if (!isRecord(serverJson)) return [];
  const meta = isRecord(serverJson._meta) ? serverJson._meta : {};
  const capabilities = isRecord(serverJson.capabilities) ? serverJson.capabilities : {};
  const introspection = isRecord(serverJson.introspection) ? serverJson.introspection : {};
  const mcp = isRecord(serverJson.mcp) ? serverJson.mcp : {};
  const metaCapabilities = isRecord(meta.capabilities) ? meta.capabilities : {};
  const metaIntrospection = isRecord(meta.introspection) ? meta.introspection : {};
  const metaMcp = isRecord(meta.mcp) ? meta.mcp : {};
  const candidates = [
    serverJson.resources,
    serverJson.resourceDefinitions,
    serverJson.mcpResources,
    capabilities.resources,
    introspection.resources,
    introspection["resources/list"],
    serverJson["resources/list"],
    mcp.resources,
    mcp["resources/list"],
    meta.resources,
    metaCapabilities.resources,
    metaIntrospection.resources,
    metaIntrospection["resources/list"],
    metaMcp.resources,
    metaMcp["resources/list"],
  ];
  const seen = new Set<string>();
  return candidates
    .flatMap(resourceCandidateLists)
    .flat()
    .filter((resource) => {
      const uri = typeof resource.uri === "string" ? resource.uri.trim() : "";
      if (!uri || seen.has(uri)) return false;
      seen.add(uri);
      return true;
    });
}

function resourceTemplatesFromServerJson(serverJson: unknown) {
  if (!isRecord(serverJson)) return [];
  const meta = isRecord(serverJson._meta) ? serverJson._meta : {};
  const introspection = isRecord(serverJson.introspection) ? serverJson.introspection : {};
  const mcp = isRecord(serverJson.mcp) ? serverJson.mcp : {};
  const metaIntrospection = isRecord(meta.introspection) ? meta.introspection : {};
  const metaMcp = isRecord(meta.mcp) ? meta.mcp : {};
  const candidates = [
    serverJson.resourceTemplates,
    serverJson.resourceTemplateDefinitions,
    serverJson["resources/templates/list"],
    introspection.resourceTemplates,
    introspection["resources/templates/list"],
    mcp.resourceTemplates,
    mcp["resources/templates/list"],
    meta.resourceTemplates,
    meta["resources/templates/list"],
    metaIntrospection.resourceTemplates,
    metaIntrospection["resources/templates/list"],
    metaMcp.resourceTemplates,
    metaMcp["resources/templates/list"],
  ];
  const seen = new Set<string>();
  return candidates
    .flatMap(resourceTemplateCandidateLists)
    .flat()
    .filter((template) => {
      const uriTemplate =
        typeof template.uriTemplate === "string" ? template.uriTemplate.trim() : "";
      if (!uriTemplate || seen.has(uriTemplate)) return false;
      seen.add(uriTemplate);
      return true;
    });
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
    next: { revalidate: 3600 },
    headers: { Accept: "application/json" },
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
  let servers: RegistryServerRead[] = [];
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

    const page = publishedRegistryServerPage(response);
    servers = mergePublishedServers(servers, page.servers);
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

  return publishedRegistryServerPage(response);
}

export function getPublicRegistryStats() {
  return registryRequest<RegistryStatsResponse>("/mcp/catalog/stats");
}

export async function countPublishedRegistryServers() {
  const response = await registryRequest<RegistryPublishedServerListResponse>("/mcp/catalog", {
    fields: "id",
    page: 1,
  });
  return response.metadata.total;
}

export async function listPublishedRegistryServerSitemapChunk(chunkIndex: number) {
  let servers: RegistryServerRead[] = [];
  const startOffset = chunkIndex * SITEMAP_CATALOG_CHUNK_SIZE;
  let cursor = String(startOffset);

  while (servers.length < SITEMAP_CATALOG_CHUNK_SIZE) {
    const response = await registryRequest<RegistryServerListResponse>("/mcp/servers", {
      cursor,
      fields: PUBLIC_CARD_FIELDS,
      limit: Math.min(PAGE_SIZE, SITEMAP_CATALOG_CHUNK_SIZE - servers.length),
    });

    const page = publishedRegistryServerPage(response);
    servers = mergePublishedServers(servers, page.servers);

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
    if (!isRegistryNotFoundError(error)) {
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

  if (tab === "tools") {
    return {
      server: baseServer,
      versions: detail.versions?.map((version) => ({
        id: version.id,
        isLatest: version.isLatest,
        title: version.title,
        tools: toolsFromServerJson(version.serverJson),
        version: version.version,
      })),
    };
  }

  if (tab === "prompts") {
    return {
      server: baseServer,
      versions: detail.versions?.map((version) => ({
        id: version.id,
        isLatest: version.isLatest,
        prompts: promptsFromServerJson(version.serverJson),
        title: version.title,
        version: version.version,
      })),
    };
  }

  if (tab === "resources") {
    return {
      server: baseServer,
      versions: detail.versions?.map((version) => ({
        id: version.id,
        isLatest: version.isLatest,
        resources: resourcesFromServerJson(version.serverJson),
        resourceTemplates: resourceTemplatesFromServerJson(version.serverJson),
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
