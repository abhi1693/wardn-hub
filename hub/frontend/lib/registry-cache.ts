import { detailTabs } from "@/lib/server-detail-tabs";

export const REGISTRY_CACHE_TAG = "registry";
export const REGISTRY_LIST_CACHE_TAG = "registry:list";

export function registryServerCacheTag(serverName: string) {
  return `registry:server:${serverName.trim()}`;
}

export function serverDetailPath(serverName: string) {
  return `/servers/${serverName.split("/").map(encodeURIComponent).join("/")}`;
}

export function serverDetailRevalidationPaths(serverName: string) {
  const basePath = serverDetailPath(serverName);
  return detailTabs.map((tab) => (tab.id === "overview" ? basePath : `${basePath}/${tab.id}`));
}
