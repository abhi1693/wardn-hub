"use client";

import type {
  AuditEventListResponse,
  AuditEventsListParams,
  AuthProviderListResponse,
  BootstrapUserCreate,
  EventDeliveryListResponse,
  EventDeliveryRead,
  EventRuleCreate,
  EventRuleListResponse,
  EventRuleRead,
  EventRuleUpdate,
  EventSecretRotateResponse,
  EventTypeListResponse,
  EventsDeliveriesListParams,
  LoginRequest,
  McpServersListParams,
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
  RegistryOwnershipClaimResponse,
  RegistryServerDetailResponse,
  RegistryServerListResponse,
  RegistryServerVersionCreate,
  RegistryServerVersionDetailResponse,
  RegistryServerVersionUpdate,
  RegistryUserDetailResponse,
  ServerSourceImportRequest,
  ServerSourceImportResponse,
  SubmissionRejectRequest,
  SubmissionRead,
  SubmissionListResponse,
  SubmissionSubmitRequest,
  SubmissionUpdate,
  SubmissionsListParams,
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
import {
  getAdminMcpServersCreateVersionUrl,
  getAdminMcpServersDeleteUrl,
  getAdminMcpServersUpdateVersionUrl,
} from "@/lib/api/generated/admin-mcp/admin-mcp";
import { getAuditEventsListUrl } from "@/lib/api/generated/audit/audit";
import {
  getAuthCreateApiTokenUrl,
  getAuthDeleteApiTokenUrl,
  getAuthListApiTokensUrl,
  getAuthListProvidersUrl,
  getAuthLoginUrl,
  getAuthLogoutUrl,
  getAuthMeUrl,
  getAuthRegisterUrl,
  getAuthUpdateApiTokenUrl,
} from "@/lib/api/generated/auth/auth";
import {
  getEventsDeliveriesGetUrl,
  getEventsDeliveriesListUrl,
  getEventsDeliveriesReplayUrl,
  getEventsRulesCreateUrl,
  getEventsRulesDeleteUrl,
  getEventsRulesGetUrl,
  getEventsRulesListUrl,
  getEventsRulesRotateSecretUrl,
  getEventsRulesTestUrl,
  getEventsRulesUpdateUrl,
  getEventsTypesListUrl,
} from "@/lib/api/generated/events/events";
import { getImportsServerSourceUrl } from "@/lib/api/generated/imports/imports";
import {
  getMcpCategoriesCreateUrl,
  getMcpCategoriesDeleteUrl,
  getMcpCategoriesListUrl,
  getMcpCategoriesUpdateUrl,
} from "@/lib/api/generated/mcp-categories/mcp-categories";
import {
  getMcpServersGetUrl,
  getMcpServersListUrl,
} from "@/lib/api/generated/mcp/mcp";
import {
  getOrganizationMembershipsListUrl,
  getOrganizationMembershipsUpdateUrl,
  getOrganizationMembershipsUpsertUrl,
  getOrganizationRolesListUrl,
  getOrganizationsCreateUrl,
  getOrganizationsListUrl,
} from "@/lib/api/generated/organizations/organizations";
import {
  getPartnersListUrl,
  getPartnersServerSupportCreateUrl,
  getPartnersServerSupportListUrl,
  getPartnersServerSupportUpdateUrl,
  getPartnersUpdateOrganizationUrl,
} from "@/lib/api/generated/partners/partners";
import {
  getSubmissionsApproveUrl,
  getSubmissionsCreateAndSubmitUrl,
  getSubmissionsDeleteUrl,
  getSubmissionsGetUrl,
  getSubmissionsListUrl,
  getSubmissionsPublishUrl,
  getSubmissionsRejectUrl,
  getSubmissionsUpdateUrl,
  getSubmissionsWithdrawUrl,
} from "@/lib/api/generated/submissions/submissions";
import {
  getUsersBootstrapUrl,
  getUsersGetUrl,
  getUsersListUrl,
  getUsersUpdateAdminFlagsUrl,
} from "@/lib/api/generated/users/users";
import type { DetailTab, ServerDetailTabResponse } from "@/lib/server-detail-tabs";
import { serverTabApiPath } from "@/lib/server-detail-tabs";

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

function formatValidationDetail(detail: unknown) {
  if (typeof detail === "string") {
    return detail;
  }
  if (!Array.isArray(detail)) {
    return "";
  }

  return detail
    .map((item) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        return "";
      }
      const record = item as Record<string, unknown>;
      const location = Array.isArray(record.loc) ? record.loc.map(String).join(".") : "";
      const message = typeof record.msg === "string" ? record.msg : "";
      return [location, message].filter(Boolean).join(": ");
    })
    .filter(Boolean)
    .join("; ");
}

function apiBaseUrl() {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "");
  if (configured) return configured;
  return API_PREFIX;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  if (!headers.has("Authorization")) {
    const token = await authBearerToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    credentials: "include",
    headers,
  });
  const body = await response.text();
  const contentType = response.headers.get("content-type") ?? "";
  const data = body && contentType.includes("application/json") ? JSON.parse(body) : {};

  if (!response.ok) {
    const detailMessage = formatValidationDetail((data as Record<string, unknown>).detail);
    const message = detailMessage || `Request failed with ${response.status} from ${response.url}`;
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

function generatedPath(generatedUrl: string) {
  const url = new URL(generatedUrl, "http://wardn-hub.local");
  const path = url.pathname.startsWith(API_PREFIX)
    ? url.pathname.slice(API_PREFIX.length) || "/"
    : url.pathname;
  return `${path}${url.search}`;
}

function generatedRequest<T>(generatedUrl: string, init?: RequestInit) {
  return request<T>(generatedPath(generatedUrl), init);
}

function optionalQueryString(value?: string) {
  return value === "" ? undefined : value;
}

async function clerkSessionToken() {
  if (typeof window === "undefined") return "";
  const clerk = (window as ClerkWindow).Clerk;
  if (!clerk?.session?.getToken) return "";
  return (await clerk.session.getToken(clerkTokenOptions())) ?? "";
}

async function authBearerToken() {
  if (typeof window === "undefined") return "";
  const clerkToken = await clerkSessionToken();
  if (clerkToken) return clerkToken;
  const localToken = window.localStorage.getItem(TOKEN_STORAGE_KEY) ?? "";
  return localToken;
}

function pathValue(value: string) {
  return value.split("/").map(encodeURIComponent).join("/");
}

export function clerkTokenOptions(): ClerkTokenOptions | undefined {
  const template = process.env.NEXT_PUBLIC_CLERK_JWT_TEMPLATE?.trim();
  return template ? { template } : undefined;
}

export function listServers(params: {
  cursor?: string;
  fields?: string;
  search?: string;
  supportLevel?: string;
  partner?: boolean;
  category?: string;
  limit?: number;
}) {
  const generatedParams: McpServersListParams = {
    cursor: optionalQueryString(params.cursor),
    fields: optionalQueryString(params.fields),
    search: optionalQueryString(params.search),
    support_level: optionalQueryString(params.supportLevel),
    partner: params.partner,
    category: optionalQueryString(params.category),
    limit: params.limit ?? 25,
  };
  return generatedRequest<RegistryServerListResponse>(getMcpServersListUrl(generatedParams));
}

export async function listPublishedServers(params: {
  cursor?: string;
  fields?: string;
  search?: string;
  supportLevel?: string;
  partner?: boolean;
  category?: string;
  limit?: number;
}) {
  const response = await listServers(params);
  return {
    ...response,
    servers: response.servers.filter((server) => Boolean(server.latestVersion)),
  };
}

export function listCategories() {
  return generatedRequest<RegistryCategoryListResponse>(getMcpCategoriesListUrl());
}

export function createCategory(payload: RegistryCategoryCreate) {
  return generatedRequest<RegistryCategoryRead>(getMcpCategoriesCreateUrl(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateCategory(categorySlug: string, payload: RegistryCategoryUpdate) {
  return generatedRequest<RegistryCategoryRead>(
    getMcpCategoriesUpdateUrl(encodeURIComponent(categorySlug)),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function deleteCategory(categorySlug: string) {
  return generatedRequest<void>(getMcpCategoriesDeleteUrl(encodeURIComponent(categorySlug)), {
    method: "DELETE",
  });
}

export function listUsers() {
  return generatedRequest<UserDirectoryListResponse>(getUsersListUrl());
}

export function listRegistryUsers() {
  return listUsers();
}

export function getRegistryUser(userId: string) {
  return generatedRequest<RegistryUserDetailResponse>(getUsersGetUrl(encodeURIComponent(userId)));
}

export function getServer(serverName: string) {
  return generatedRequest<RegistryServerDetailResponse>(getMcpServersGetUrl(pathValue(serverName)));
}

export function getServerDetailTab(serverName: string, tab: DetailTab) {
  return request<ServerDetailTabResponse>(serverTabApiPath(serverName, tab));
}

export function claimServerOwnership(serverName: string) {
  return generatedRequest<RegistryOwnershipClaimResponse>(
    `/mcp/servers/${pathValue(serverName)}/claim`,
    { method: "POST" },
  );
}

export function createServerVersion(payload: RegistryServerVersionCreate) {
  return generatedRequest<RegistryServerVersionDetailResponse>(
    getAdminMcpServersCreateVersionUrl(),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function updateServerVersion(
  serverName: string,
  version: string,
  payload: RegistryServerVersionUpdate,
) {
  return generatedRequest<RegistryServerVersionDetailResponse>(
    getAdminMcpServersUpdateVersionUrl(pathValue(serverName), encodeURIComponent(version)),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function deleteServer(serverName: string) {
  return generatedRequest<void>(getAdminMcpServersDeleteUrl(pathValue(serverName)), {
    method: "DELETE",
  });
}

export function archiveServer(serverName: string) {
  return deleteServer(serverName);
}

export function listSubmissions(params?: SubmissionsListParams) {
  return generatedRequest<SubmissionListResponse>(getSubmissionsListUrl(params));
}

export function getSubmission(submissionId: string) {
  return generatedRequest<SubmissionRead>(getSubmissionsGetUrl(encodeURIComponent(submissionId)));
}

export function createAndSubmitSubmission(payload: SubmissionSubmitRequest) {
  return generatedRequest<SubmissionRead>(getSubmissionsCreateAndSubmitUrl(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function importServerSource(payload: ServerSourceImportRequest) {
  return generatedRequest<ServerSourceImportResponse>(getImportsServerSourceUrl(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateSubmission(submissionId: string, payload: SubmissionUpdate) {
  return generatedRequest<SubmissionRead>(
    getSubmissionsUpdateUrl(encodeURIComponent(submissionId)),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function deleteSubmission(submissionId: string) {
  return generatedRequest<void>(getSubmissionsDeleteUrl(encodeURIComponent(submissionId)), {
    method: "DELETE",
  });
}

export function listPartnerOrganizations() {
  return generatedRequest<PartnerOrganizationListResponse>(getPartnersListUrl());
}

export function listPartnerSupport(organizationId: string) {
  return generatedRequest<PartnerServerSupportListResponse>(
    getPartnersServerSupportListUrl(encodeURIComponent(organizationId)),
  );
}

export function createOrganization(payload: OrganizationCreate) {
  return generatedRequest<OrganizationRead>(getOrganizationsCreateUrl(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function listOrganizations() {
  return generatedRequest<OrganizationListResponse>(getOrganizationsListUrl());
}

export function listOrganizationRoles(organizationId: string) {
  return generatedRequest<OrganizationRoleListResponse>(
    getOrganizationRolesListUrl(encodeURIComponent(organizationId)),
  );
}

export function listOrganizationMemberships(organizationId: string) {
  return generatedRequest<OrganizationMembershipListResponse>(
    getOrganizationMembershipsListUrl(encodeURIComponent(organizationId)),
  );
}

export function upsertOrganizationMembership(
  organizationId: string,
  payload: OrganizationMembershipCreate,
) {
  return generatedRequest<OrganizationMembershipRead>(
    getOrganizationMembershipsUpsertUrl(encodeURIComponent(organizationId)),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function updateOrganizationMembership(
  organizationId: string,
  userId: string,
  payload: OrganizationMembershipUpdate,
) {
  return generatedRequest<OrganizationMembershipRead>(
    getOrganizationMembershipsUpdateUrl(
      encodeURIComponent(organizationId),
      encodeURIComponent(userId),
    ),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function listAuditEvents() {
  const params: AuditEventsListParams = { limit: 50 };
  return generatedRequest<AuditEventListResponse>(getAuditEventsListUrl(params));
}

export function listEventTypes() {
  return generatedRequest<EventTypeListResponse>(getEventsTypesListUrl());
}

export function listEventRules() {
  return generatedRequest<EventRuleListResponse>(getEventsRulesListUrl());
}

export function getEventRule(ruleId: string) {
  return generatedRequest<EventRuleRead>(getEventsRulesGetUrl(encodeURIComponent(ruleId)));
}

export function createEventRule(payload: EventRuleCreate) {
  return generatedRequest<EventRuleRead>(getEventsRulesCreateUrl(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateEventRule(ruleId: string, payload: EventRuleUpdate) {
  return generatedRequest<EventRuleRead>(getEventsRulesUpdateUrl(encodeURIComponent(ruleId)), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteEventRule(ruleId: string) {
  return generatedRequest<void>(getEventsRulesDeleteUrl(encodeURIComponent(ruleId)), {
    method: "DELETE",
  });
}

export function testEventRule(ruleId: string) {
  return generatedRequest<EventDeliveryRead>(getEventsRulesTestUrl(encodeURIComponent(ruleId)), {
    method: "POST",
  });
}

export function rotateEventRuleSecret(ruleId: string) {
  return generatedRequest<EventSecretRotateResponse>(
    getEventsRulesRotateSecretUrl(encodeURIComponent(ruleId)),
    { method: "POST" },
  );
}

export function listEventDeliveries(params: EventsDeliveriesListParams = { limit: 50 }) {
  return generatedRequest<EventDeliveryListResponse>(getEventsDeliveriesListUrl(params));
}

export function getEventDelivery(deliveryId: string) {
  return generatedRequest<EventDeliveryRead>(
    getEventsDeliveriesGetUrl(encodeURIComponent(deliveryId)),
  );
}

export function replayEventDelivery(deliveryId: string) {
  return generatedRequest<EventDeliveryRead>(
    getEventsDeliveriesReplayUrl(encodeURIComponent(deliveryId)),
    { method: "POST" },
  );
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
  return generatedRequest<AuthProviderListResponse>(getAuthListProvidersUrl());
}

export function login(payload: LoginRequest) {
  return generatedRequest<UserRead>(getAuthLoginUrl(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function registerUser(payload: UserCreate) {
  return generatedRequest<UserRead>(getAuthRegisterUrl(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function currentUser() {
  return generatedRequest<UserRead>(getAuthMeUrl());
}

export function currentUserWithToken(token: string) {
  return generatedRequest<UserRead>(getAuthMeUrl(), {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export function bootstrap(payload: BootstrapUserCreate) {
  return generatedRequest<UserRead>(getUsersBootstrapUrl(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateUserAdminFlags(userId: string, payload: UserAdminUpdate) {
  return generatedRequest<UserDirectoryRead>(
    getUsersUpdateAdminFlagsUrl(encodeURIComponent(userId)),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function logout() {
  return generatedRequest<void>(getAuthLogoutUrl(), { method: "POST" });
}

export async function signOutExternalAuth(options?: ClerkSignOutOptions) {
  if (typeof window === "undefined") return;
  await (window as ClerkWindow).Clerk?.signOut?.(options);
}

export function listApiTokens() {
  return generatedRequest<UserAPITokenListResponse>(getAuthListApiTokensUrl());
}

export function createApiToken(payload: UserAPITokenCreate) {
  return generatedRequest<UserAPITokenCreated>(getAuthCreateApiTokenUrl(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateApiToken(tokenId: string, payload: UserAPITokenUpdate) {
  return generatedRequest<UserAPITokenRead>(
    getAuthUpdateApiTokenUrl(encodeURIComponent(tokenId)),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function deleteApiToken(tokenId: string) {
  return generatedRequest<void>(getAuthDeleteApiTokenUrl(encodeURIComponent(tokenId)), {
    method: "DELETE",
  });
}

export function submissionAction(
  submissionId: string,
  action: "withdraw" | "approve" | "publish",
) {
  const encodedSubmissionId = encodeURIComponent(submissionId);
  type SubmissionAction = typeof action;
  const urlByAction = {
    withdraw: getSubmissionsWithdrawUrl,
    approve: getSubmissionsApproveUrl,
    publish: getSubmissionsPublishUrl,
  } satisfies Record<SubmissionAction, (submissionId: string) => string>;
  return generatedRequest<SubmissionRead>(urlByAction[action](encodedSubmissionId), {
    method: "POST",
  });
}

export function rejectSubmission(submissionId: string, payload: SubmissionRejectRequest) {
  return generatedRequest<SubmissionRead>(
    getSubmissionsRejectUrl(encodeURIComponent(submissionId)),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function updatePartnerOrganization(
  organizationId: string,
  payload: PartnerOrganizationUpdate,
) {
  return generatedRequest<PartnerOrganizationRead>(
    getPartnersUpdateOrganizationUrl(encodeURIComponent(organizationId)),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function createPartnerSupport(
  organizationId: string,
  payload: PartnerServerSupportCreate,
) {
  return generatedRequest<PartnerServerSupportRead>(
    getPartnersServerSupportCreateUrl(encodeURIComponent(organizationId)),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function updatePartnerSupport(supportId: string, payload: PartnerServerSupportUpdate) {
  return generatedRequest<PartnerServerSupportRead>(
    getPartnersServerSupportUpdateUrl(encodeURIComponent(supportId)),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export { API_PREFIX as DEFAULT_API_BASE_URL };
