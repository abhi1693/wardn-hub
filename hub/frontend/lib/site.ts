const DEFAULT_SITE_URL =
  process.env.NODE_ENV === "production" ? "https://hub.wardnai.dev" : "http://localhost:3000";
const DEFAULT_PUBLIC_REGISTRY_URL = "https://hub.wardnai.dev";

function stripTrailingSlash(value: string) {
  return value.replace(/\/+$/, "");
}

function ensureUrlHasProtocol(value: string) {
  if (/^https?:\/\//i.test(value)) return value;
  if (value.startsWith("localhost") || value.startsWith("127.0.0.1")) {
    return `http://${value}`;
  }
  return `https://${value}`;
}

function computeSiteUrl() {
  const raw =
    process.env.NEXT_PUBLIC_SITE_URL?.trim() ||
    process.env.WARDN_HUB_REGISTRY_PUBLIC_BASE_URL?.trim() ||
    process.env.NEXT_PUBLIC_APP_URL?.trim() ||
    DEFAULT_SITE_URL;
  return stripTrailingSlash(ensureUrlHasProtocol(raw)) || DEFAULT_SITE_URL;
}

const SITE_URL = computeSiteUrl();

function computePublicRegistryUrl() {
  const raw =
    process.env.NEXT_PUBLIC_REGISTRY_PUBLIC_BASE_URL?.trim() ||
    process.env.WARDN_HUB_REGISTRY_PUBLIC_BASE_URL?.trim() ||
    DEFAULT_PUBLIC_REGISTRY_URL;
  return stripTrailingSlash(ensureUrlHasProtocol(raw)) || DEFAULT_PUBLIC_REGISTRY_URL;
}

const PUBLIC_REGISTRY_URL = computePublicRegistryUrl();

export const siteConfig = {
  description:
    "Wardn Hub is a community-driven directory for discovering, comparing, and sharing Model Context Protocol servers.",
  keywords: [
    "MCP registry",
    "Model Context Protocol",
    "MCP servers",
    "MCP server aggregator",
    "server.json",
    "MCP server directory",
    "community MCP servers",
    "AI tool registry",
  ],
  name: "Wardn Hub",
  tagline: "Community directory for MCP servers.",
  url: SITE_URL,
} as const;

export function resolveSiteUrl() {
  return SITE_URL;
}

export function resolvePublicRegistryUrl() {
  return PUBLIC_REGISTRY_URL;
}

export function absoluteUrl(path: string) {
  return new URL(path, SITE_URL).toString();
}

export function publicRegistryUrl(path: string) {
  return new URL(path, PUBLIC_REGISTRY_URL).toString();
}
