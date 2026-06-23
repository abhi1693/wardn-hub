"use client";

import type {
  AuditEventListResponse,
  BootstrapUserCreate,
  LoginRequest,
  NamespaceClaimCreate,
  NamespaceClaimDecision,
  NamespaceClaimListResponse,
  NamespaceClaimRead,
  PartnerOrganizationListResponse,
  PartnerOrganizationRead,
  PartnerOrganizationUpdate,
  PartnerServerSupportCreate,
  PartnerServerSupportListResponse,
  PartnerServerSupportRead,
  RegistryCategoryListResponse,
  RegistryServerDetailResponse,
  RegistryServerListResponse,
  SubmissionRejectRequest,
  SubmissionRead,
  SubmissionListResponse,
  UserCreate,
  UserRead,
} from "@/lib/api/generated/model";

const DEFAULT_API_BASE_URL = "http://localhost:8001/api/v1";
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
  return (
    process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? DEFAULT_API_BASE_URL
  );
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

export function listServers(params: {
  search?: string;
  supportLevel?: string;
  partner?: boolean;
  category?: string;
  limit?: number;
}) {
  return request<RegistryServerListResponse>(
    `/mcp/servers${query({
      search: params.search,
      support_level: params.supportLevel,
      partner: params.partner,
      category: params.category,
      limit: params.limit ?? 25,
    })}`,
  );
}

export function listCategories() {
  return request<RegistryCategoryListResponse>("/mcp/categories");
}

export function getServer(serverName: string) {
  return request<RegistryServerDetailResponse>(
    `/mcp/servers/${encodeURIComponent(serverName)}`,
  );
}

export function listSubmissions() {
  return request<SubmissionListResponse>("/submissions");
}

export function listNamespaceClaims() {
  return request<NamespaceClaimListResponse>("/namespaces/claims");
}

export function listPartnerOrganizations() {
  return request<PartnerOrganizationListResponse>("/partners");
}

export function listPartnerSupport(organizationId: string) {
  return request<PartnerServerSupportListResponse>(
    `/partners/organizations/${organizationId}/server-support`,
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

export function createNamespaceClaim(payload: NamespaceClaimCreate) {
  return request<NamespaceClaimRead>("/namespaces/claims", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function namespaceDecision(
  claimId: string,
  action: "verify" | "fail",
  payload: NamespaceClaimDecision,
) {
  return request<NamespaceClaimRead>(`/namespaces/claims/${claimId}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function revokeNamespaceClaim(claimId: string) {
  return request<NamespaceClaimRead>(`/namespaces/claims/${claimId}/revoke`, { method: "POST" });
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

export { DEFAULT_API_BASE_URL };
