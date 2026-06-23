"use client";

import type {
  AuditEventListResponse,
  BootstrapUserCreate,
  LoginRequest,
  PartnerOrganizationListResponse,
  PartnerOrganizationRead,
  PartnerOrganizationUpdate,
  PartnerServerSupportCreate,
  PartnerServerSupportListResponse,
  PartnerServerSupportRead,
  RegistryCategoryListResponse,
  RegistryServerDetailResponse,
  RegistryServerListResponse,
  SubmissionCreate,
  SubmissionRejectRequest,
  SubmissionRead,
  SubmissionListResponse,
  SubmissionUpdate,
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
  const configured =
    process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? DEFAULT_API_BASE_URL;
  if (typeof window === "undefined") return configured;

  const pageHost = window.location.hostname;
  if (pageHost === "localhost" || pageHost === "127.0.0.1") return configured;

  try {
    const url = new URL(configured);
    if (url.hostname === "localhost" || url.hostname === "127.0.0.1") {
      url.hostname = pageHost;
      url.protocol = window.location.protocol;
      return url.toString().replace(/\/$/, "");
    }
  } catch {
    return configured;
  }

  return configured;
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

export { DEFAULT_API_BASE_URL };
