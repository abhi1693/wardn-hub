import { timingSafeEqual } from "node:crypto";

import { revalidatePath, revalidateTag } from "next/cache";
import { NextResponse } from "next/server";

import {
  REGISTRY_CACHE_TAG,
  REGISTRY_LIST_CACHE_TAG,
  registryServerCacheTag,
  serverDetailRevalidationPaths,
} from "@/lib/registry-cache";

const MAX_SERVER_NAMES = 250;
const PUBLIC_REGISTRY_PATHS: { path: string; type?: "page" }[] = [
  { path: "/" },
  { path: "/categories" },
  { path: "/categories/[categorySlug]", type: "page" },
  { path: "/integrations/[integrationSlug]", type: "page" },
  { path: "/mcp-servers" },
  { path: "/registries/[registrySlug]", type: "page" },
  { path: "/search" },
  { path: "/transports/[transportSlug]", type: "page" },
  { path: "/llms.txt" },
  { path: "/llms-full.txt" },
  { path: "/sitemap.xml" },
  { path: "/sitemap-main.xml" },
  { path: "/sitemap-catalog.xml" },
];

type RevalidateRegistryPayload = {
  all?: unknown;
  serverNames?: unknown;
};

function jsonResponse(body: Record<string, unknown>, status = 200) {
  return NextResponse.json(body, {
    headers: {
      "Cache-Control": "private, max-age=0, must-revalidate",
    },
    status,
  });
}

function configuredToken() {
  return process.env.WARDN_HUB_REVALIDATE_TOKEN?.trim() ?? "";
}

function bearerToken(request: Request) {
  const authorization = request.headers.get("authorization")?.trim() ?? "";
  const prefix = "Bearer ";
  return authorization.startsWith(prefix) ? authorization.slice(prefix.length).trim() : "";
}

function requestToken(request: Request) {
  return request.headers.get("x-wardn-revalidate-token")?.trim() || bearerToken(request);
}

function tokenMatches(actual: string, expected: string) {
  const actualBytes = Buffer.from(actual);
  const expectedBytes = Buffer.from(expected);
  return actualBytes.length === expectedBytes.length && timingSafeEqual(actualBytes, expectedBytes);
}

function authorize(request: Request) {
  const token = configuredToken();
  if (!token) {
    return jsonResponse({ detail: "Registry revalidation is not configured." }, 503);
  }
  if (!tokenMatches(requestToken(request), token)) {
    return jsonResponse({ detail: "Unauthorized." }, 401);
  }
  return null;
}

async function readPayload(request: Request): Promise<RevalidateRegistryPayload> {
  try {
    const payload = await request.json();
    return payload && typeof payload === "object" && !Array.isArray(payload)
      ? (payload as RevalidateRegistryPayload)
      : {};
  } catch {
    return {};
  }
}

function normalizeServerNames(value: unknown) {
  const rawNames = Array.isArray(value) ? value : typeof value === "string" ? [value] : [];
  const names = new Set<string>();
  const invalid: string[] = [];

  for (const item of rawNames) {
    if (typeof item !== "string") continue;
    const name = item.trim();
    const parts = name.split("/");
    if (parts.length !== 2 || parts.some((part) => !part.trim())) {
      invalid.push(name);
      continue;
    }
    names.add(name);
  }

  return {
    invalid,
    names: Array.from(names).slice(0, MAX_SERVER_NAMES),
    truncated: names.size > MAX_SERVER_NAMES,
  };
}

function revalidateRegistry() {
  const tags = [REGISTRY_CACHE_TAG, REGISTRY_LIST_CACHE_TAG];
  for (const tag of tags) {
    revalidateTag(tag, { expire: 0 });
  }
  for (const { path, type } of PUBLIC_REGISTRY_PATHS) {
    if (type) {
      revalidatePath(path, type);
    } else {
      revalidatePath(path);
    }
  }
  return { paths: PUBLIC_REGISTRY_PATHS.map(({ path }) => path), tags };
}

function revalidateRegistryServers(serverNames: string[]) {
  const tags = new Set<string>();
  const paths = new Set<string>();

  for (const serverName of serverNames) {
    tags.add(registryServerCacheTag(serverName));
    for (const path of serverDetailRevalidationPaths(serverName)) {
      paths.add(path);
    }
  }

  for (const tag of tags) {
    revalidateTag(tag, { expire: 0 });
  }
  for (const path of paths) {
    revalidatePath(path, "page");
  }

  return { paths: Array.from(paths), tags: Array.from(tags) };
}

export async function POST(request: Request) {
  const unauthorized = authorize(request);
  if (unauthorized) return unauthorized;

  const payload = await readPayload(request);
  const all = payload.all === true;
  const { invalid, names, truncated } = normalizeServerNames(payload.serverNames);

  if (invalid.length > 0) {
    return jsonResponse({ detail: "Invalid registry server names.", invalid }, 400);
  }
  if (!all && names.length === 0) {
    return jsonResponse({ detail: "Provide all=true or at least one server name." }, 400);
  }

  const registryResult = all ? revalidateRegistry() : { paths: [], tags: [] };
  const serverResult = names.length > 0 ? revalidateRegistryServers(names) : { paths: [], tags: [] };
  const paths = Array.from(new Set([...registryResult.paths, ...serverResult.paths]));
  const tags = Array.from(new Set([...registryResult.tags, ...serverResult.tags]));

  return jsonResponse({
    all,
    paths,
    serverNames: names,
    tags,
    truncated,
  });
}
