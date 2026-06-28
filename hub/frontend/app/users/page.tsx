"use client";

import Link from "next/link";
import { Pencil, RotateCcw, Trash2, User, X } from "lucide-react";
import { useEffect, useState } from "react";

import { PageLoader } from "@/components/page-loader";
import { PublicHeader } from "@/components/site-header";
import {
  currentUser,
  getServer,
  HubApiError,
  listUsers,
  listPublishedServers,
  type RegistryUserRead,
  updateUserAdminFlags,
} from "@/lib/api/hub";
import type { UserRead } from "@/lib/api/generated/model";
import { usersFromServerDetails, usersFromServers } from "@/lib/registry-users";

type LoadState = "loading" | "ready" | "error";
type RoleKey = "isActive" | "isSuperuser" | "isGlobalModerator" | "isGlobalPartnerManager";

const roleOptions: { description: string; key: RoleKey; label: string }[] = [
  {
    description: "Can sign in and use the product.",
    key: "isActive",
    label: "Active",
  },
  {
    description: "Full administrative access.",
    key: "isSuperuser",
    label: "Superuser",
  },
  {
    description: "Can approve or reject submissions.",
    key: "isGlobalModerator",
    label: "Moderator",
  },
  {
    description: "Can manage partner organizations.",
    key: "isGlobalPartnerManager",
    label: "Partner manager",
  },
];

function userHref(userId: string) {
  return `/users/${encodeURIComponent(userId)}`;
}

function userLabel(user: RegistryUserRead) {
  return user.displayName || user.name || user.login || user.email || user.id;
}

function userDetail(user: RegistryUserRead) {
  if (user.email && user.email !== userLabel(user)) return user.email;
  return user.login;
}

function updatePayload(key: RoleKey, value: boolean) {
  if (key === "isActive") return { isActive: value };
  if (key === "isSuperuser") return { isSuperuser: value };
  if (key === "isGlobalModerator") return { isGlobalModerator: value };
  return { isGlobalPartnerManager: value };
}

function accessBadges(user: RegistryUserRead) {
  const badges = [
    {
      label: user.isActive === false ? "Inactive" : "Active",
      tone: user.isActive === false ? "danger" : "success",
    },
  ];
  if (user.isSuperuser) badges.push({ label: "Superuser", tone: "admin" });
  if (user.isGlobalModerator) badges.push({ label: "Moderator", tone: "review" });
  if (user.isGlobalPartnerManager) badges.push({ label: "Partner manager", tone: "partner" });
  return badges;
}

export default function UsersPage() {
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [currentAccount, setCurrentAccount] = useState<UserRead | null>(null);
  const [users, setUsers] = useState<RegistryUserRead[]>([]);
  const [editingUserId, setEditingUserId] = useState("");
  const [updatingAction, setUpdatingAction] = useState("");

  const canManageUsers = Boolean(currentAccount?.is_superuser);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setState("loading");
      setError("");
      currentUser()
        .then((user) => {
          setCurrentAccount(user);
          return listUsers();
        })
        .catch((caught) => {
          if (caught instanceof HubApiError && caught.status === 401) {
            setCurrentAccount(null);
            return listUsers();
          }
          throw caught;
        })
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

  async function toggleRole(user: RegistryUserRead, key: RoleKey, value: boolean) {
    setUpdatingAction(`${user.id}:${key}`);
    setError("");
    setNotice("");
    try {
      const updated = await updateUserAdminFlags(user.id, updatePayload(key, value));
      setUsers((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setNotice(`Updated ${userLabel(updated)}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to update user.");
    } finally {
      setUpdatingAction("");
    }
  }

  async function deactivateUser(user: RegistryUserRead) {
    const confirmed = window.confirm(`Deactivate ${userLabel(user)}? They will no longer be able to sign in.`);
    if (!confirmed) return;
    await toggleRole(user, "isActive", false);
  }

  async function activateUser(user: RegistryUserRead) {
    await toggleRole(user, "isActive", true);
  }

  return (
    <div className="server-detail-page">
      <PublicHeader />

      <main className="server-detail-main">
        <section className="category-page-header">
          <div>
            <h1>Users</h1>
            <p>
              {canManageUsers
                ? "Browse users and manage global access."
                : "Browse public MCP server publishers and maintainers."}
            </p>
          </div>
        </section>

        {notice ? <div className="notice">{notice}</div> : null}
        {state === "ready" && error ? <div className="error-banner">{error}</div> : null}

        {state === "loading" ? <PageLoader label="Loading users" /> : null}

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
              <article className={`user-card ${user.isActive === false ? "inactive" : ""}`} key={user.id}>
                <Link className="user-card-main" href={userHref(user.id)}>
                  <span
                    className={`user-card-avatar ${user.avatarUrl ? "user-card-avatar-image" : ""}`}
                    style={user.avatarUrl ? { backgroundImage: `url("${user.avatarUrl}")` } : undefined}
                  >
                    {user.avatarUrl ? null : <User size={20} />}
                  </span>
                  <span>
                    <strong>{userLabel(user)}</strong>
                    <small>{userDetail(user)}</small>
                    {canManageUsers ? (
                      <span className="user-card-badges">
                        {accessBadges(user).map((badge) => (
                          <span className={`user-card-badge ${badge.tone}`} key={badge.label}>
                            {badge.label}
                          </span>
                        ))}
                      </span>
                    ) : null}
                  </span>
                </Link>

                {canManageUsers ? (
                  <div className="user-card-actions">
                    <button
                      aria-label={`Edit access for ${userLabel(user)}`}
                      className="icon-button"
                      onClick={() => setEditingUserId((current) => (current === user.id ? "" : user.id))}
                      title="Edit access"
                      type="button"
                    >
                      {editingUserId === user.id ? <X size={16} /> : <Pencil size={16} />}
                    </button>
                    {user.isActive === false ? (
                      <button
                        aria-label={`Activate ${userLabel(user)}`}
                        className="icon-button success"
                        disabled={updatingAction === `${user.id}:isActive`}
                        onClick={() => void activateUser(user)}
                        title="Activate user"
                        type="button"
                      >
                        <RotateCcw size={16} />
                      </button>
                    ) : (
                      <button
                        aria-label={`Deactivate ${userLabel(user)}`}
                        className="icon-button danger"
                        disabled={user.id === currentAccount?.id || updatingAction === `${user.id}:isActive`}
                        onClick={() => void deactivateUser(user)}
                        title="Deactivate user"
                        type="button"
                      >
                        <Trash2 size={16} />
                      </button>
                    )}
                  </div>
                ) : null}

                {editingUserId === user.id && canManageUsers ? (
                  <div className="user-card-access">
                    {roleOptions.map((option) => {
                      const checked = Boolean(user[option.key]);
                      const selfCritical =
                        user.id === currentAccount?.id &&
                        (option.key === "isActive" || option.key === "isSuperuser");
                      const saving = updatingAction === `${user.id}:${option.key}`;
                      return (
                        <label className="user-access-toggle" key={option.key}>
                          <input
                            checked={checked}
                            disabled={selfCritical || saving}
                            onChange={(event) => void toggleRole(user, option.key, event.target.checked)}
                            type="checkbox"
                          />
                          <span>
                            <strong>{saving ? "Saving" : option.label}</strong>
                            <small>{option.description}</small>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        ) : null}
      </main>
    </div>
  );
}
