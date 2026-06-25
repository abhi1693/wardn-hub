"use client";

import { useParams } from "next/navigation";
import { User } from "lucide-react";
import { useEffect, useState } from "react";

import { ServerCard } from "@/components/server-card";
import { PublicHeader } from "@/components/site-header";
import {
  getServer,
  getRegistryUser,
  HubApiError,
  listPublishedServers,
  type RegistryUserRead,
} from "@/lib/api/hub";
import type { RegistryServerRead } from "@/lib/api/generated/model";
import {
  serversForUser,
  serversForUserFromDetails,
  usersFromServerDetails,
  usersFromServers,
} from "@/lib/registry-users";

type LoadState = "loading" | "ready" | "error";

function userLabel(user: RegistryUserRead | null) {
  if (!user) return "User";
  return user.name || user.login || user.id;
}

export default function UserDetailPage() {
  const params = useParams<{ userId?: string }>();
  const userId = params.userId ?? "";
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [user, setUser] = useState<RegistryUserRead | null>(null);
  const [servers, setServers] = useState<RegistryServerRead[]>([]);

  useEffect(() => {
    if (!userId) return;

    const timeoutId = window.setTimeout(() => {
      setState("loading");
      setError("");
      getRegistryUser(userId)
        .then((response) => {
          setUser(response.user);
          setServers(response.servers);
          setState("ready");
        })
        .catch(async (caught) => {
          if (!(caught instanceof HubApiError) || caught.status !== 404) throw caught;
          const response = await listPublishedServers({ limit: 100 });
          let fallbackUser = usersFromServers(response.servers).find((item) => item.id === userId);
          let fallbackServers = serversForUser(response.servers, userId);

          if (!fallbackUser || fallbackServers.length === 0) {
            const detailResults = await Promise.allSettled(
              response.servers.map((server) => getServer(server.name)),
            );
            const details = detailResults
              .filter((result) => result.status === "fulfilled")
              .map((result) => result.value);
            fallbackUser =
              fallbackUser ?? usersFromServerDetails(details).find((item) => item.id === userId);
            fallbackServers = serversForUserFromDetails(details, userId);
          }

          if (!fallbackUser) throw caught;
          setUser(fallbackUser);
          setServers(fallbackServers);
          setState("ready");
        })
        .catch((caught) => {
          setError(caught instanceof Error ? caught.message : "Unable to load user.");
          setState("error");
        });
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, [userId]);

  return (
    <div className="server-detail-page">
      <PublicHeader />

      <main className="server-detail-main">
        <section className="user-page-header">
          <span
            className={`user-page-avatar ${user?.avatarUrl ? "user-page-avatar-image" : ""}`}
            style={user?.avatarUrl ? { backgroundImage: `url("${user.avatarUrl}")` } : undefined}
          >
            {user?.avatarUrl ? null : <User size={30} />}
          </span>
          <div>
            <h1>{userLabel(user)}</h1>
            {user?.login ? <p>{user.login}</p> : null}
          </div>
        </section>

        {state === "loading" ? (
          <div className="empty-state">
            <div className="empty-title">Loading</div>
            <div className="empty-detail">Fetching user servers.</div>
          </div>
        ) : null}

        {state === "error" ? (
          <div className="empty-state">
            <div className="empty-title">User unavailable</div>
            <div className="empty-detail">{error}</div>
          </div>
        ) : null}

        {state === "ready" && servers.length === 0 ? (
          <div className="empty-state">
            <div className="empty-title">No published servers</div>
            <div className="empty-detail">No published MCP servers are listed for this user.</div>
          </div>
        ) : null}

        {state === "ready" && servers.length > 0 ? (
          <div className="server-grid">
            {servers.map((server) => (
              <ServerCard key={server.id} server={server} />
            ))}
          </div>
        ) : null}
      </main>
    </div>
  );
}
