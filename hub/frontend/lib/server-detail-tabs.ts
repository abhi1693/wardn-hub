import type {
  ActorSummary,
  PartnerSupportSummary,
  RegistryCategoryRead,
  RegistryNamespace,
  RegistryServerRead,
  RegistryServerVersionRead,
  RegistryTrustReport,
} from "@/lib/api/generated/model";

export type DetailTab = "overview" | "tools" | "prompts" | "schema" | "score";

export const detailTabs: { id: DetailTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "tools", label: "Tools" },
  { id: "prompts", label: "Prompts" },
  { id: "schema", label: "Schema" },
  { id: "score", label: "Score" },
];

export function detailTabFromValue(value: string | null | undefined): DetailTab {
  return detailTabs.some((tab) => tab.id === value) ? (value as DetailTab) : "overview";
}

export type ServerTabServer = Pick<
  RegistryServerRead,
  | "icons"
  | "id"
  | "name"
  | "title"
> &
  Partial<
    Pick<
      RegistryServerRead,
      "categories" | "description" | "registryNamespace" | "repository" | "updatedAt" | "websiteUrl"
    >
  >;

export type ServerSummaryResponse = Pick<
  RegistryServerRead,
  "description" | "icons" | "id" | "name" | "title"
>;

export type ServerTabVersion = Pick<
  RegistryServerVersionRead,
  "id" | "isLatest" | "title" | "version"
> & {
  description?: string;
  documentation?: string;
  packages?: Record<string, unknown>[];
  partnerSupport?: PartnerSupportSummary[];
  publishedAt?: string;
  publishedBy?: ActorSummary | null;
  qualityScore?: number | null;
  prompts?: Record<string, unknown>[];
  registryNamespace?: RegistryNamespace;
  remotes?: Record<string, unknown>[];
  repository?: Record<string, unknown> | null;
  serverJson?: Record<string, unknown>;
  tools?: Record<string, unknown>[];
  trustReport?: RegistryTrustReport | null;
  updatedAt?: string;
  websiteUrl?: string;
};

export type ServerDetailTabResponse = {
  server: ServerTabServer & {
    categories?: RegistryCategoryRead[];
  };
  versions?: ServerTabVersion[];
  partnerSupport?: PartnerSupportSummary[];
};

export function serverTabApiPath(serverName: string, tab: DetailTab) {
  return `/mcp/servers/${serverName.split("/").map(encodeURIComponent).join("/")}/tabs/${tab}`;
}

export function serverDetailTabPath(serverName: string, tab: DetailTab) {
  const serverPath = `/servers/${serverName.split("/").map(encodeURIComponent).join("/")}`;
  return tab === "overview" ? serverPath : `${serverPath}/${tab}`;
}
