import type {
  RegistryServerListResponse,
  RegistryServerRead,
} from "@/lib/api/generated/model";

export type PublishedRegistryServerPage = {
  nextCursor: string;
  servers: RegistryServerRead[];
};

export function deduplicatePublishedServers(servers: RegistryServerRead[]) {
  const seen = new Set<string>();
  return servers.filter((server) => {
    if (!server.latestVersion || seen.has(server.id)) return false;
    seen.add(server.id);
    return true;
  });
}

export function publishedRegistryServerPage(
  response: RegistryServerListResponse,
): PublishedRegistryServerPage {
  return {
    nextCursor: response.metadata.nextCursor ?? "",
    servers: deduplicatePublishedServers(response.servers),
  };
}

export function mergePublishedServers(
  current: RegistryServerRead[],
  incoming: RegistryServerRead[],
) {
  return deduplicatePublishedServers([...current, ...incoming]);
}
