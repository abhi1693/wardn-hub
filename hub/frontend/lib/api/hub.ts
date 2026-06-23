"use client";

import type {
  AuditEventListResponse,
  NamespaceClaimListResponse,
  PartnerOrganizationListResponse,
  PartnerServerSupportListResponse,
  RegistryServerDetailResponse,
  RegistryServerListResponse,
  SubmissionListResponse,
} from "@/lib/api/generated/model";

const DEFAULT_API_BASE_URL = "http://localhost:8001/api/v1";

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
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
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
  limit?: number;
}) {
  return request<RegistryServerListResponse>(
    `/mcp/servers${query({
      search: params.search,
      support_level: params.supportLevel,
      partner: params.partner,
      limit: params.limit ?? 25,
    })}`,
  );
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

export { DEFAULT_API_BASE_URL };
