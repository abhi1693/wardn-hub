"use client";

import type {
  AuditEventListResponse,
  AuthProviderListResponse,
  BootstrapUserCreate,
  LoginRequest,
  OrganizationCreate,
  OrganizationMembershipCreate,
  OrganizationMembershipListResponse,
  OrganizationMembershipRead,
  OrganizationMembershipUpdate,
  OrganizationListResponse,
  OrganizationRead,
  OrganizationRoleListResponse,
  PartnerOrganizationListResponse,
  PartnerOrganizationRead,
  PartnerOrganizationUpdate,
  PartnerServerSupportCreate,
  PartnerServerSupportListResponse,
  PartnerServerSupportRead,
  PartnerServerSupportUpdate,
  RegistryCategoryCreate,
  RegistryCategoryListResponse,
  RegistryCategoryRead,
  RegistryCategoryUpdate,
  RegistryServerDetailResponse,
  RegistryServerListResponse,
  RegistryServerVersionCreate,
  RegistryServerVersionDetailResponse,
  RegistryServerVersionUpdate,
  RegistryUserDetailResponse,
  ServerSourceImportRequest,
  ServerSourceImportResponse,
  SubmissionCreate,
  SubmissionRejectRequest,
  SubmissionRead,
  SubmissionListResponse,
  SubmissionUpdate,
  UserAPITokenCreate,
  UserAPITokenCreated,
  UserAPITokenListResponse,
  UserAPITokenRead,
  UserAPITokenUpdate,
  UserAdminUpdate,
  UserCreate,
  UserDirectoryListResponse,
  UserDirectoryRead,
  UserRead,
} from "@/lib/api/generated/model";

export type RegistryUserRead = UserDirectoryRead;

const API_PREFIX = "/api/v1";
const TOKEN_STORAGE_KEY = "wardn_hub_api_token";

type ClerkWindow = Window & {
  Clerk?: {
    session?: {
      getToken: (options?: ClerkTokenOptions) => Promise<string | null>;
    } | null;
    signOut?: (options?: ClerkSignOutOptions) => Promise<void>;
  };
};

type ClerkTokenOptions = {
  template?: string;
};

type ClerkSignOutOptions = {
  redirectUrl?: string;
};

export class HubApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "HubApiError";
    this.status = status;
  }
}

function apiBaseUrl() {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "");
  if (configured) return configured;
  return API_PREFIX;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await authBearerToken();
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  const body = await response.text();
  const contentType = response.headers.get("content-type") ?? "";
  const data = body && contentType.includes("application/json") ? JSON.parse(body) : {};

  if (!response.ok) {
    const message =
      typeof data.detail === "string"
        ? data.detail
        : `Request failed with ${response.status} from ${response.url}`;
    throw new HubApiError(response.status, message);
  }

  if (body && !contentType.includes("application/json")) {
    throw new HubApiError(
      response.status,
      `Expected JSON from ${response.url}, received ${contentType || "unknown content type"}`,
    );
  }

  return data as T;
}

async function clerkSessionToken() {
  if (typeof window === "undefined") return "";
  const clerk = (window as ClerkWindow).Clerk;
  if (!clerk?.session?.getToken) return "";
  return (await clerk.session.getToken(clerkTokenOptions())) ?? "";
}

async function authBearerToken() {
  if (typeof window === "undefined") return "";
  const localToken = window.localStorage.getItem(TOKEN_STORAGE_KEY) ?? "";
  if (localToken) return localToken;
  return clerkSessionToken();
}

function query(params: Record<string, string | number | boolean | undefined>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  });
  const value = search.toString();
  return value ? `?${value}` : "";
}

function pathValue(value: string) {
  return value.split("/").map(encodeURIComponent).join("/");
}

export function clerkTokenOptions(): ClerkTokenOptions | undefined {
  const template = process.env.NEXT_PUBLIC_CLERK_JWT_TEMPLATE?.trim();
  return template ? { template } : undefined;
}

export function listServers(params: {
  search?: string;
  supportLevel?: string;
  partner?: boolean;
  category?: string;
  limit?: number;
  status?: string;
}) {
  return request<RegistryServerListResponse>(
    `/mcp/servers${query({
      search: params.search,
      support_level: params.supportLevel,
      partner: params.partner,
      category: params.category,
      limit: params.limit ?? 25,
      status: params.status,
    })}`,
  );
}

export async function listPublishedServers(params: {
  search?: string;
  supportLevel?: string;
  partner?: boolean;
  category?: string;
  limit?: number;
}) {
  const response = await listServers({ ...params, status: "active" });
  return {
    ...response,
    servers: response.servers.filter((server) => Boolean(server.latestVersion)),
  };
}

export function listCategories() {
  return request<RegistryCategoryListResponse>("/mcp/categories");
}

export function createCategory(payload: RegistryCategoryCreate) {
  return request<RegistryCategoryRead>("/mcp/categories", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateCategory(categorySlug: string, payload: RegistryCategoryUpdate) {
  return request<RegistryCategoryRead>(`/mcp/categories/${encodeURIComponent(categorySlug)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteCategory(categorySlug: string) {
  return request<void>(`/mcp/categories/${encodeURIComponent(categorySlug)}`, {
    method: "DELETE",
  });
}

export function listUsers() {
  return request<UserDirectoryListResponse>("/users");
}

export function listRegistryUsers() {
  return listUsers();
}

export function getRegistryUser(userId: string) {
  return request<RegistryUserDetailResponse>(`/users/${encodeURIComponent(userId)}`);
}

export function getServer(serverName: string) {
  return request<RegistryServerDetailResponse>(
    `/mcp/servers/${pathValue(serverName)}`,
  );
}

export function createServerVersion(payload: RegistryServerVersionCreate) {
  return request<RegistryServerVersionDetailResponse>("/admin/mcp/servers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateServerVersion(
  serverName: string,
  version: string,
  payload: RegistryServerVersionUpdate,
) {
  return request<RegistryServerVersionDetailResponse>(
    `/admin/mcp/servers/${pathValue(serverName)}/versions/${encodeURIComponent(version)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function deleteServer(serverName: string) {
  return request<void>(`/admin/mcp/servers/${pathValue(serverName)}`, {
    method: "DELETE",
  });
}

export function archiveServer(serverName: string) {
  return deleteServer(serverName);
}

export function listSubmissions() {
  return request<SubmissionListResponse>("/submissions");
}

export function getSubmission(submissionId: string) {
  return request<SubmissionRead>(`/submissions/${submissionId}`);
}

export function createSubmission(payload: SubmissionCreate) {
  return request<SubmissionRead>("/submissions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function importServerSource(payload: ServerSourceImportRequest) {
  return request<ServerSourceImportResponse>("/imports/server-source", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateSubmission(submissionId: string, payload: SubmissionUpdate) {
  return request<SubmissionRead>(`/submissions/${submissionId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteSubmission(submissionId: string) {
  return request<void>(`/submissions/${submissionId}`, {
    method: "DELETE",
  });
}

export function listPartnerOrganizations() {
  return request<PartnerOrganizationListResponse>("/partners");
}

export function listPartnerSupport(organizationId: string) {
  return request<PartnerServerSupportListResponse>(
    `/partners/organizations/${organizationId}/server-support`,
  );
}

export function createOrganization(payload: OrganizationCreate) {
  return request<OrganizationRead>("/organizations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function listOrganizations() {
  return request<OrganizationListResponse>("/organizations");
}

export function listOrganizationRoles(organizationId: string) {
  return request<OrganizationRoleListResponse>(`/organizations/${organizationId}/roles`);
}

export function listOrganizationMemberships(organizationId: string) {
  return request<OrganizationMembershipListResponse>(
    `/organizations/${organizationId}/memberships`,
  );
}

export function upsertOrganizationMembership(
  organizationId: string,
  payload: OrganizationMembershipCreate,
) {
  return request<OrganizationMembershipRead>(`/organizations/${organizationId}/memberships`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateOrganizationMembership(
  organizationId: string,
  userId: string,
  payload: OrganizationMembershipUpdate,
) {
  return request<OrganizationMembershipRead>(
    `/organizations/${organizationId}/memberships/${userId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function listAuditEvents() {
  return request<AuditEventListResponse>("/audit/events?limit=50");
}

export function setApiToken(token: string) {
  if (token.trim()) {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token.trim());
  } else {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

export function getApiToken() {
  return typeof window === "undefined" ? "" : window.localStorage.getItem(TOKEN_STORAGE_KEY) ?? "";
}

export function listAuthProviders() {
  return request<AuthProviderListResponse>("/auth/providers");
}

export function login(payload: LoginRequest) {
  return request<UserRead>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function registerUser(payload: UserCreate) {
  return request<UserRead>("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function currentUser() {
  return request<UserRead>("/auth/me");
}

export function currentUserWithToken(token: string) {
  return request<UserRead>("/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export function bootstrap(payload: BootstrapUserCreate) {
  return request<UserRead>("/users/bootstrap", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateUserAdminFlags(userId: string, payload: UserAdminUpdate) {
  return request<UserDirectoryRead>(`/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function logout() {
  return request<void>("/auth/logout", { method: "POST" });
}

export async function signOutExternalAuth(options?: ClerkSignOutOptions) {
  if (typeof window === "undefined") return;
  await (window as ClerkWindow).Clerk?.signOut?.(options);
}

export function listApiTokens() {
  return request<UserAPITokenListResponse>("/auth/api-tokens");
}

export function createApiToken(payload: UserAPITokenCreate) {
  return request<UserAPITokenCreated>("/auth/api-tokens", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateApiToken(tokenId: string, payload: UserAPITokenUpdate) {
  return request<UserAPITokenRead>(`/auth/api-tokens/${encodeURIComponent(tokenId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteApiToken(tokenId: string) {
  return request<void>(`/auth/api-tokens/${encodeURIComponent(tokenId)}`, {
    method: "DELETE",
  });
}

export function submissionAction(
  submissionId: string,
  action: "submit" | "withdraw" | "approve" | "publish",
) {
  return request<SubmissionRead>(`/submissions/${submissionId}/${action}`, { method: "POST" });
}

export function rejectSubmission(submissionId: string, payload: SubmissionRejectRequest) {
  return request<SubmissionRead>(`/submissions/${submissionId}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updatePartnerOrganization(
  organizationId: string,
  payload: PartnerOrganizationUpdate,
) {
  return request<PartnerOrganizationRead>(`/partners/organizations/${organizationId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function createPartnerSupport(
  organizationId: string,
  payload: PartnerServerSupportCreate,
) {
  return request<PartnerServerSupportRead>(
    `/partners/organizations/${organizationId}/server-support`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function updatePartnerSupport(supportId: string, payload: PartnerServerSupportUpdate) {
  return request<PartnerServerSupportRead>(`/partners/server-support/${supportId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export { API_PREFIX as DEFAULT_API_BASE_URL };
