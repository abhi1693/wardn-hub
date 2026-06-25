"use client";

import Link from "next/link";
import { User } from "lucide-react";
import { useEffect, useState } from "react";

import { PublicHeader } from "@/components/site-header";
import {
  getServer,
  HubApiError,
  listPublishedServers,
  listRegistryUsers,
  type RegistryUserRead,
} from "@/lib/api/hub";
import { usersFromServerDetails, usersFromServers } from "@/lib/registry-users";

type LoadState = "loading" | "ready" | "error";

function userHref(userId: string) {
  return `/users/${encodeURIComponent(userId)}`;
}

function userLabel(user: RegistryUserRead) {
  return user.name || user.login || user.id;
}

export default function UsersPage() {
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [users, setUsers] = useState<RegistryUserRead[]>([]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setState("loading");
      setError("");
      listRegistryUsers()
        .then((response) => {
          setUsers(response.users);
          setState("ready");
        })
        .catch(async (caught) => {
          if (!(caught instanceof HubApiError) || caught.status !== 404) throw caught;
          const response = await listPublishedServers({ limit: 100 });
          let fallbackUsers = usersFromServers(response.servers);
          if (fallbackUsers.length === 0) {
            const detailResults = await Promise.allSettled(
              response.servers.map((server) => getServer(server.name)),
            );
            fallbackUsers = usersFromServerDetails(
              detailResults
                .filter((result) => result.status === "fulfilled")
                .map((result) => result.value),
            );
          }
          setUsers(fallbackUsers);
          setState("ready");
        })
        .catch((caught) => {
          setError(caught instanceof Error ? caught.message : "Unable to load users.");
          setState("error");
        });
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, []);

  return (
    <div className="server-detail-page">
      <PublicHeader />

      <main className="server-detail-main">
        <section className="category-page-header">
          <div>
            <h1>Users</h1>
            <p>Browse public MCP server publishers and maintainers.</p>
          </div>
        </section>

        {state === "loading" ? (
          <div className="empty-state">
            <div className="empty-title">Loading</div>
            <div className="empty-detail">Fetching users.</div>
          </div>
        ) : null}

        {state === "error" ? (
          <div className="empty-state">
            <div className="empty-title">Users unavailable</div>
            <div className="empty-detail">{error}</div>
          </div>
        ) : null}

        {state === "ready" && users.length === 0 ? (
          <div className="empty-state">
            <div className="empty-title">No users</div>
            <div className="empty-detail">No public registry users are available.</div>
          </div>
        ) : null}

        {state === "ready" && users.length > 0 ? (
          <div className="user-grid">
            {users.map((user) => (
              <Link className="user-card" href={userHref(user.id)} key={user.id}>
                <span
                  className={`user-card-avatar ${user.avatarUrl ? "user-card-avatar-image" : ""}`}
                  style={user.avatarUrl ? { backgroundImage: `url("${user.avatarUrl}")` } : undefined}
                >
                  {user.avatarUrl ? null : <User size={20} />}
                </span>
                <span>
                  <strong>{userLabel(user)}</strong>
                  <small>{user.login}</small>
                </span>
              </Link>
            ))}
          </div>
        ) : null}
      </main>
    </div>
  );
}
