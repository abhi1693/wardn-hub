import type {
  ActorSummary,
  PartnerSupportSummary,
  RegistryCategoryRead,
  RegistryNamespace,
  RegistryServerRead,
  RegistryServerVersionRead,
  RegistryTrustReport,
} from "@/lib/api/generated/model";
import {
  isRecord,
  promptsFromServerJson,
  records,
  resourceTemplatesFromServerJson,
  resourcesFromServerJson,
  toolsFromServerJson,
} from "@/lib/server-json-capabilities";

export type DetailTab = "overview" | "tools" | "prompts" | "resources" | "schema" | "score";

export const detailTabs: { id: DetailTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "tools", label: "Tools" },
  { id: "prompts", label: "Prompts" },
  { id: "resources", label: "Resources" },
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
  resourceTemplates?: Record<string, unknown>[];
  resources?: Record<string, unknown>[];
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

export function serverTabVersionForDisplay(
  versions?: ServerTabVersion[],
  selectedVersionId = "",
) {
  const values = versions ?? [];
  return (
    values.find((version) => version.id === selectedVersionId) ??
    values.find((version) => version.isLatest) ??
    values[0]
  );
}

export function versionTargets(version?: ServerTabVersion) {
  const explicitTools = records(version?.tools);
  const explicitPrompts = records(version?.prompts);
  const explicitResources = records(version?.resources);
  const explicitResourceTemplates = records(version?.resourceTemplates);
  return {
    packages: records(version?.packages),
    prompts:
      explicitPrompts.length > 0 ? explicitPrompts : promptsFromServerJson(version?.serverJson),
    resourceTemplates:
      explicitResourceTemplates.length > 0
        ? explicitResourceTemplates
        : resourceTemplatesFromServerJson(version?.serverJson),
    resources:
      explicitResources.length > 0
        ? explicitResources
        : resourcesFromServerJson(version?.serverJson),
    remotes: records(version?.remotes),
    tools: explicitTools.length > 0 ? explicitTools : toolsFromServerJson(version?.serverJson),
  };
}

export function hasServerDetailTabData(tab: DetailTab, version?: ServerTabVersion) {
  if (tab === "overview" || tab === "score") return true;
  const targets = versionTargets(version);
  if (tab === "tools") return targets.tools.length > 0;
  if (tab === "prompts") return targets.prompts.length > 0;
  if (tab === "resources") {
    return targets.resources.length + targets.resourceTemplates.length > 0;
  }
  if (tab === "schema") {
    const manifest = isRecord(version?.serverJson) ? version.serverJson : null;
    const schema = typeof manifest?.$schema === "string" ? manifest.$schema.trim() : "";
    return targets.packages.length + targets.remotes.length > 0 || Boolean(schema);
  }
  return false;
}

export function visibleDetailTabs(version?: ServerTabVersion) {
  return detailTabs.filter((tab) => hasServerDetailTabData(tab.id, version));
}

export function serverTabApiPath(serverName: string, tab: DetailTab) {
  return `/mcp/servers/${serverName.split("/").map(encodeURIComponent).join("/")}/tabs/${tab}`;
}

export function serverDetailTabPath(serverName: string, tab: DetailTab) {
  const serverPath = `/servers/${serverName.split("/").map(encodeURIComponent).join("/")}`;
  return tab === "overview" ? serverPath : `${serverPath}/${tab}`;
}
