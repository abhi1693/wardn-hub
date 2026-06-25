import type { RegistryUserRead } from "@/lib/api/hub";
import type {
  ActorSummary,
  RegistryServerDetailResponse,
  RegistryServerRead,
  RegistryServerVersionRead,
} from "@/lib/api/generated/model";

function actorToUser(actor?: ActorSummary | null): RegistryUserRead | null {
  if (!actor || actor.type !== "User") return null;
  return {
    id: actor.id,
    login: actor.login,
    name: actor.name,
    avatarUrl: actor.avatarUrl,
    htmlUrl: actor.htmlUrl,
  };
}

function serverUsers(server: RegistryServerRead) {
  return [
    actorToUser(server.owner),
    actorToUser(server.createdBy),
    actorToUser(server.updatedBy),
    actorToUser(server.latestVersion?.publishedBy),
  ].filter((user): user is RegistryUserRead => user !== null);
}

function versionUsers(version: RegistryServerVersionRead) {
  return [
    actorToUser(version.owner),
    actorToUser(version.createdBy),
    actorToUser(version.updatedBy),
    actorToUser(version.publishedBy),
  ].filter((user): user is RegistryUserRead => user !== null);
}

function detailUsers(detail: RegistryServerDetailResponse) {
  return [
    ...serverUsers(detail.server),
    ...(detail.versions ?? []).flatMap((version) => versionUsers(version)),
  ];
}

function uniqueUsers(users: RegistryUserRead[]) {
  const unique = new Map<string, RegistryUserRead>();
  users.forEach((user) => {
    if (!unique.has(user.id)) unique.set(user.id, user);
  });

  return [...unique.values()].sort((left, right) => {
    const leftLabel = left.name || left.login || left.id;
    const rightLabel = right.name || right.login || right.id;
    return leftLabel.localeCompare(rightLabel);
  });
}

export function usersFromServers(servers: RegistryServerRead[]) {
  return uniqueUsers(servers.flatMap((server) => serverUsers(server)));
}

export function usersFromServerDetails(details: RegistryServerDetailResponse[]) {
  return uniqueUsers(details.flatMap((detail) => detailUsers(detail)));
}

export function serversForUser(servers: RegistryServerRead[], userId: string) {
  return servers.filter((server) => serverUsers(server).some((user) => user.id === userId));
}

export function serversForUserFromDetails(details: RegistryServerDetailResponse[], userId: string) {
  return details
    .filter((detail) => detailUsers(detail).some((user) => user.id === userId))
    .map((detail) => detail.server);
}
