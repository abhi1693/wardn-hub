"use client";

import type {
  AuditEventListResponse,
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
  RegistryCategoryListResponse,
  RegistryServerDetailResponse,
  RegistryServerListResponse,
  RegistryServerVersionCreate,
  RegistryServerVersionDetailResponse,
  RegistryServerVersionUpdate,
  ServerSourceImportRequest,
  ServerSourceImportResponse,
  SubmissionCreate,
  SubmissionRejectRequest,
  SubmissionRead,
  SubmissionListResponse,
  SubmissionUpdate,
  UserCreate,
  UserRead,
} from "@/lib/api/generated/model";

export interface RegistryUserRead {
  id: string;
  login: string;
  name?: string;
  avatarUrl?: string;
  htmlUrl?: string;
}

export interface RegistryUserListResponse {
  users: RegistryUserRead[];
}

export interface RegistryUserDetailResponse {
  user: RegistryUserRead;
  servers: RegistryServerListResponse["servers"];
  metadata: RegistryServerListResponse["metadata"];
}

const API_PREFIX = "/api/v1";
const DEFAULT_API_BASE_URL = `http://localhost:8000${API_PREFIX}`;
const TOKEN_STORAGE_KEY = "wardn_hub_api_token";

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

  if (typeof window === "undefined") return DEFAULT_API_BASE_URL;

  const pageHost = window.location.hostname;
  if (pageHost === "localhost" || pageHost === "127.0.0.1") return DEFAULT_API_BASE_URL;

  return `${window.location.origin}${API_PREFIX}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token =
    typeof window === "undefined" ? "" : window.localStorage.getItem(TOKEN_STORAGE_KEY) ?? "";
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
  const data = body ? JSON.parse(body) : {};

  if (!response.ok) {
    const message =
      typeof data.detail === "string" ? data.detail : `Request failed with ${response.status}`;
    throw new HubApiError(response.status, message);
  }

  return data as T;
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

export function listRegistryUsers() {
  return request<RegistryUserListResponse>("/mcp/users");
}

export function getRegistryUser(userId: string) {
  return request<RegistryUserDetailResponse>(`/mcp/users/${encodeURIComponent(userId)}`);
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

export function bootstrap(payload: BootstrapUserCreate) {
  return request<UserRead>("/users/bootstrap", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function logout() {
  return request<void>("/auth/logout", { method: "POST" });
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

export { DEFAULT_API_BASE_URL };
