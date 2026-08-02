import type {
  RegistryCategoryRead,
  RegistryServerDetailResponse,
  RegistryServerRead,
  SkillDetailResponse,
  SkillRead,
} from "@/lib/api/generated/model";
import { serverDetailPath } from "@/lib/public-registry";
import type { ServerDetailTabResponse } from "@/lib/server-detail-tabs";
import { absoluteUrl, siteConfig } from "@/lib/site";

type JsonLdValue =
  | JsonLdValue[]
  | boolean
  | number
  | string
  | { [key: string]: JsonLdValue | null | undefined }
  | null
  | undefined;

type BreadcrumbItem = {
  name: string;
  url: string;
};

function stringValue(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item),
      )
    : [];
}

function urlValue(value: unknown) {
  const text = stringValue(value);
  return /^https?:\/\//i.test(text) ? text : "";
}

function dateValue(value: unknown) {
  const text = stringValue(value);
  if (!text) return "";
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString();
}

function newestDate(values: unknown[]) {
  const dates = values
    .map(dateValue)
    .filter(Boolean)
    .sort((left, right) => right.localeCompare(left));
  return dates[0] ?? "";
}

function cleanJsonLd(value: JsonLdValue): JsonLdValue {
  if (Array.isArray(value)) {
    const values = value.map((item) => cleanJsonLd(item)).filter((item) => item !== undefined);
    return values.length > 0 ? values : undefined;
  }

  if (value && typeof value === "object") {
    const entries = Object.entries(value)
      .map(([key, item]) => [key, cleanJsonLd(item as JsonLdValue)] as const)
      .filter(([, item]) => item !== undefined);
    return entries.length > 0 ? Object.fromEntries(entries) : undefined;
  }

  if (typeof value === "string") return value || undefined;
  return value ?? undefined;
}

function jsonLdMarkup(value: JsonLdValue) {
  return JSON.stringify(cleanJsonLd(value)).replace(/</g, "\\u003c");
}

export function JsonLdScript({ data, id }: { data: JsonLdValue; id: string }) {
  return (
    <script
      dangerouslySetInnerHTML={{ __html: jsonLdMarkup(data) }}
      id={id}
      type="application/ld+json"
    />
  );
}

export function websiteJsonLd() {
  const siteUrl = absoluteUrl("/");
  const organizationId = `${siteUrl}#organization`;
  const websiteId = `${siteUrl}#website`;
  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@id": organizationId,
        "@type": "Organization",
        description: siteConfig.description,
        logo: {
          "@type": "ImageObject",
          height: 512,
          url: absoluteUrl("/wardn-brand-512x512.png"),
          width: 512,
        },
        name: siteConfig.name,
        url: siteUrl,
      },
      {
        "@id": websiteId,
        "@type": "WebSite",
        alternateName: "Wardn",
        description: siteConfig.description,
        name: siteConfig.name,
        publisher: { "@id": organizationId },
        url: siteUrl,
      },
    ],
  };
}

export function breadcrumbJsonLd(items: BreadcrumbItem[], id: string) {
  return {
    "@context": "https://schema.org",
    "@id": id,
    "@type": "BreadcrumbList",
    itemListElement: items.map((item, index) => ({
      "@type": "ListItem",
      item: item.url,
      name: item.name,
      position: index + 1,
    })),
  };
}

export function categoryIndexJsonLd(categories: RegistryCategoryRead[]) {
  const url = absoluteUrl("/categories");
  const siteUrl = absoluteUrl("/");
  return {
    "@context": "https://schema.org",
    "@graph": [
      breadcrumbJsonLd(
        [
          { name: siteConfig.name, url: absoluteUrl("/") },
          { name: "Categories", url },
        ],
        `${url}#breadcrumb`,
      ),
      {
        "@id": `${url}#collection`,
        "@type": "CollectionPage",
        description: "Browse community-curated Model Context Protocol servers by category on Wardn Hub.",
        isPartOf: { "@id": `${siteUrl}#website` },
        mainEntity: {
          "@id": `${url}#item-list`,
          "@type": "ItemList",
          itemListElement: categories.map((category, index) => ({
            "@type": "ListItem",
            item: {
              "@id": absoluteUrl(`/categories/${encodeURIComponent(category.slug)}`),
              "@type": "CollectionPage",
              description: category.description,
              name: category.name,
              url: absoluteUrl(`/categories/${encodeURIComponent(category.slug)}`),
            },
            position: index + 1,
          })),
          name: "MCP server categories",
          numberOfItems: categories.length,
        },
        name: "MCP server categories",
        url,
      },
      {
        "@id": `${url}#dataset`,
        "@type": "Dataset",
        description:
          "Wardn Hub category index for discovering Model Context Protocol servers by use case.",
        creator: { "@id": `${siteUrl}#organization` },
        includedInDataCatalog: { "@id": `${siteUrl}#website` },
        keywords: ["Model Context Protocol", "MCP servers", "MCP categories"],
        name: "Wardn Hub MCP server category dataset",
        publisher: { "@id": `${siteUrl}#organization` },
        url,
        variableMeasured: ["category", "description", "sort order"],
      },
    ],
  };
}

function serverListItemJsonLd(server: RegistryServerRead) {
  const url = absoluteUrl(serverDetailPath(server.name));
  return {
    "@id": `${url}#server`,
    "@type": "SoftwareSourceCode",
    codeRepository: repositoryUrl(server.repository),
    description: server.description,
    keywords: uniqueStrings([
      "Model Context Protocol",
      "MCP server",
      ...(server.categories ?? []).map((category) => category.name),
    ]),
    name: server.title || server.name,
    url,
  };
}

export function registryIndexJsonLd(servers: RegistryServerRead[], path = "/mcp-servers") {
  const url = absoluteUrl(path);
  const siteUrl = absoluteUrl("/");
  const dateModified = newestDate(servers.map((server) => server.updatedAt));
  return {
    "@context": "https://schema.org",
    "@graph": [
      breadcrumbJsonLd(
        [
          { name: siteConfig.name, url: absoluteUrl("/") },
          { name: "MCP Servers", url },
        ],
        `${url}#breadcrumb`,
      ),
      {
        "@id": `${url}#collection`,
        "@type": "CollectionPage",
        dateModified,
        description: siteConfig.description,
        isPartOf: { "@id": `${siteUrl}#website` },
        mainEntity: {
          "@id": `${url}#item-list`,
          "@type": "ItemList",
          itemListElement: servers.map((server, index) => ({
            "@type": "ListItem",
            item: serverListItemJsonLd(server),
            position: index + 1,
          })),
          name: "Published MCP servers",
          numberOfItems: servers.length,
        },
        name: "MCP Servers",
        url,
      },
      {
        "@id": `${url}#dataset`,
        "@type": "Dataset",
        dateModified,
        description:
          "Wardn Hub public catalog dataset of published Model Context Protocol servers with install metadata, package targets, remote endpoints, transport metadata, environment variables, namespace verification, review status, and Wardn Score.",
        creator: { "@id": `${siteUrl}#organization` },
        includedInDataCatalog: { "@id": `${siteUrl}#website` },
        keywords: [
          "Model Context Protocol",
          "trusted MCP server directory",
          "MCP registry",
          "MCP servers",
          "Wardn Score",
          "MCP install metadata",
        ],
        name: "Wardn Hub trusted MCP server dataset",
        publisher: { "@id": `${siteUrl}#organization` },
        url,
        variableMeasured: [
          "server name",
          "description",
          "category",
          "package target",
          "remote endpoint",
          "transport",
          "environment variable",
          "namespace verification",
          "review status",
          "quality score",
        ],
      },
    ],
  };
}

export function categoryDetailJsonLd(params: {
  category?: RegistryCategoryRead;
  categoryName: string;
  canonicalPath: string;
  servers: RegistryServerRead[];
}) {
  const url = absoluteUrl(params.canonicalPath);
  const siteUrl = absoluteUrl("/");
  const dateModified = newestDate(params.servers.map((server) => server.updatedAt));
  return {
    "@context": "https://schema.org",
    "@graph": [
      breadcrumbJsonLd(
        [
          { name: siteConfig.name, url: absoluteUrl("/") },
          { name: "Categories", url: absoluteUrl("/categories") },
          { name: params.categoryName, url },
        ],
        `${url}#breadcrumb`,
      ),
      {
        "@id": `${url}#collection`,
        "@type": "CollectionPage",
        dateModified,
        description:
          params.category?.description ||
          `Community-curated MCP servers in the ${params.categoryName} category on Wardn Hub.`,
        isPartOf: { "@id": `${siteUrl}#website` },
        mainEntity: {
          "@id": `${url}#item-list`,
          "@type": "ItemList",
          itemListElement: params.servers.map((server, index) => ({
            "@type": "ListItem",
            item: serverListItemJsonLd(server),
            position: index + 1,
          })),
          name: `${params.categoryName} MCP servers`,
          numberOfItems: params.servers.length,
        },
        name: `${params.categoryName} MCP servers`,
        url,
      },
      {
        "@id": `${url}#dataset`,
        "@type": "Dataset",
        dateModified,
        description:
          params.category?.description ||
          `Wardn Hub dataset of published ${params.categoryName} MCP servers.`,
        creator: { "@id": `${siteUrl}#organization` },
        includedInDataCatalog: { "@id": `${siteUrl}#website` },
        keywords: ["Model Context Protocol", "MCP servers", params.categoryName],
        name: `${params.categoryName} MCP server dataset`,
        publisher: { "@id": `${siteUrl}#organization` },
        url,
        variableMeasured: [
          "server name",
          "description",
          "package target",
          "remote endpoint",
          "quality score",
        ],
      },
    ],
  };
}

function repositoryUrl(value: unknown) {
  return stringValue(recordValue(value).url);
}

function packageTargetJsonLd(packageTarget: Record<string, unknown>, index: number) {
  const transport = recordValue(packageTarget.transport);
  const identifier =
    stringValue(packageTarget.identifier) ||
    stringValue(packageTarget.package) ||
    stringValue(packageTarget.name);
  const registryType = stringValue(packageTarget.registryType) || stringValue(packageTarget.type);
  const version = stringValue(packageTarget.version);
  const command = stringValue(transport.command);
  const args = Array.isArray(transport.args) ? transport.args.map(String).filter(Boolean) : [];

  return {
    "@type": "SoftwareSourceCode",
    codeSampleType: registryType,
    name: identifier || `Package target ${index + 1}`,
    programmingLanguage: registryType,
    runtimePlatform: stringValue(transport.type),
    version,
    targetProduct: command ? [command, ...args].join(" ") : undefined,
  };
}

function remoteTargetPropertyValue(remoteTarget: Record<string, unknown>, index: number) {
  const endpoint = stringValue(remoteTarget.url);
  return {
    "@type": "PropertyValue",
    name: stringValue(remoteTarget.name) || `Remote endpoint ${index + 1}`,
    value: endpoint
      ? `${stringValue(remoteTarget.type) || stringValue(remoteTarget.transport) || "remote"}: ${endpoint}`
      : stringValue(remoteTarget.type) || stringValue(remoteTarget.transport) || "remote",
  };
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

function readableReviewItem(value: unknown) {
  if (typeof value === "string") return value.trim();
  const record = recordValue(value);
  return [
    stringValue(record.flag),
    stringValue(record.name),
    stringValue(record.value),
    stringValue(record.default),
    stringValue(record.description),
  ]
    .filter(Boolean)
    .join(" - ");
}

function reviewListValues(value: unknown) {
  return Array.isArray(value) ? uniqueStrings(value.map(readableReviewItem)) : [];
}

function sourceReviewRecord(manifest: unknown) {
  const meta = recordValue(recordValue(manifest)._meta);
  const sourceReview = recordValue(meta.sourceReview);
  const llmReview = recordValue(sourceReview.llm);
  const humanReview = recordValue(sourceReview.human);
  if (Object.keys(llmReview).length > 0) return llmReview;
  if (Object.keys(humanReview).length > 0) return humanReview;
  return sourceReview;
}

function environmentVariableNames(
  packages: Record<string, unknown>[],
  remotes: Record<string, unknown>[],
  sourceReview: Record<string, unknown>,
) {
  return uniqueStrings([
    ...packages.flatMap((packageTarget) =>
      records(packageTarget.environmentVariables).map((envVar) => stringValue(envVar.name)),
    ),
    ...remotes.flatMap((remoteTarget) =>
      records(remoteTarget.environmentVariables).map((envVar) => stringValue(envVar.name)),
    ),
    ...reviewListValues(sourceReview.environmentVariables).map((value) => value.split(" - ")[0]),
  ]);
}

function commandArgumentNames(
  packages: Record<string, unknown>[],
  sourceReview: Record<string, unknown>,
) {
  return uniqueStrings([
    ...packages.flatMap((packageTarget) =>
      records(packageTarget.packageArguments).map(
        (argument) =>
          stringValue(argument.flag) ||
          stringValue(argument.name) ||
          stringValue(argument.value),
      ),
    ),
    ...reviewListValues(sourceReview.commandArguments),
  ]);
}

function transportNames(packages: Record<string, unknown>[], remotes: Record<string, unknown>[]) {
  return uniqueStrings([
    ...packages.map(
      (packageTarget) => stringValue(recordValue(packageTarget.transport).type) || "stdio",
    ),
    ...remotes.map((remoteTarget) => stringValue(remoteTarget.type) || "remote"),
  ]);
}

export function serverDetailJsonLd(
  detail: RegistryServerDetailResponse | ServerDetailTabResponse,
  canonicalPath: string,
) {
  const server = detail.server;
  const latestVersion =
    detail.versions?.find((version) => version.isLatest) ?? detail.versions?.[0];
  const repository = latestVersion?.repository ?? server.repository;
  const repositoryHref = repositoryUrl(repository);
  const serverDocumentation = "documentation" in server ? server.documentation : "";
  const documentation = latestVersion?.documentation || serverDocumentation || "";
  const documentationHref = urlValue(documentation);
  const websiteUrl = latestVersion?.websiteUrl || server.websiteUrl || "";
  const serverLatestVersion = "latestVersion" in server ? server.latestVersion : null;
  const version = latestVersion?.version || serverLatestVersion?.version || "";
  const packages = records(latestVersion?.packages);
  const remotes = records(latestVersion?.remotes);
  const manifest = recordValue(latestVersion?.serverJson);
  const sourceReview = sourceReviewRecord(manifest);
  const environmentVariables = environmentVariableNames(packages, remotes, sourceReview);
  const commandArguments = commandArgumentNames(packages, sourceReview);
  const transports = transportNames(packages, remotes);
  const categories = server.categories ?? [];
  const title = server.title || server.name;
  const registryNamespace = server.registryNamespace;
  const url = absoluteUrl(canonicalPath);
  const siteUrl = absoluteUrl("/");
  const dateModified = dateValue(latestVersion?.updatedAt) || dateValue(server.updatedAt);

  return {
    "@context": "https://schema.org",
    "@graph": [
      breadcrumbJsonLd(
        [
          { name: siteConfig.name, url: absoluteUrl("/") },
          { name: title, url },
        ],
        `${url}#breadcrumb`,
      ),
      {
        "@id": `${url}#webpage`,
        "@type": "WebPage",
        breadcrumb: { "@id": `${url}#breadcrumb` },
        dateModified,
        description: server.description,
        isPartOf: { "@id": `${siteUrl}#website` },
        mainEntity: { "@id": `${url}#server` },
        name: `${title} | ${siteConfig.name}`,
        url,
      },
      {
        "@id": `${url}#server`,
        "@type": "SoftwareSourceCode",
        additionalProperty: [
          registryNamespace?.namespace
            ? {
                "@type": "PropertyValue",
                name: "MCP registry namespace",
                value: registryNamespace.namespace,
              }
            : undefined,
          registryNamespace?.verificationStatus
            ? {
                "@type": "PropertyValue",
                name: "MCP registry namespace verification status",
                value: registryNamespace.verificationStatus,
              }
            : undefined,
          registryNamespace?.verificationMethod
            ? {
                "@type": "PropertyValue",
                name: "MCP registry namespace verification method",
                value: registryNamespace.verificationMethod,
              }
            : undefined,
          ...remotes.map(remoteTargetPropertyValue),
        ],
        alternateName: server.name,
        codeRepository: repositoryHref,
        dateModified,
        description: server.description,
        hasPart: packages.map(packageTargetJsonLd),
        keywords: uniqueStrings([
          "Model Context Protocol",
          "MCP server",
          ...categories.map((category) => category.name),
          ...transports,
          ...environmentVariables,
          ...commandArguments,
        ]),
        name: title,
        runtimePlatform: transports,
        sameAs: [repositoryHref, websiteUrl].filter(Boolean),
        version,
        subjectOf: documentationHref
          ? { "@type": "CreativeWork", url: documentationHref }
          : undefined,
        url,
      },
    ],
  };
}

function skillDetailPathFromId(skillId: string) {
  return `/skills/${skillId.split("/").map(encodeURIComponent).join("/")}`;
}

function skillSourcePathFromSource(source: string) {
  return `/skills/${source.split("/").map(encodeURIComponent).join("/")}`;
}

function skillSourceOwnerPath(source: string) {
  const owner = source.split("/", 1)[0] || source;
  return `/skills/${encodeURIComponent(owner)}`;
}

function skillWorkJsonLd(skill: SkillRead, url = absoluteUrl(skillDetailPathFromId(skill.id))) {
  const categories = skill.categories ?? [];
  return {
    "@id": `${url}#skill`,
    "@type": "CreativeWork",
    additionalProperty: [
      {
        "@type": "PropertyValue",
        name: "Install count",
        value: skill.installs,
      },
      skill.auditStatus
        ? {
            "@type": "PropertyValue",
            name: "Skill audit status",
            value: skill.auditStatus,
          }
        : undefined,
      typeof skill.auditScore === "number"
        ? {
            "@type": "PropertyValue",
            name: "Skill audit score",
            value: skill.auditScore,
          }
        : undefined,
      skill.auditRank
        ? {
            "@type": "PropertyValue",
            name: "Skill audit rank",
            value: skill.auditRank,
          }
        : undefined,
    ],
    description: skill.description,
    genre: categories.map((category) => category.name),
    isBasedOn: skill.sourceUrl,
    keywords: uniqueStrings([
      "agent skill",
      "AI agent workflow",
      ...categories.map((category) => category.name),
    ]),
    name: skill.name || skill.slug,
    url,
  };
}

export function skillIndexJsonLd(skills: SkillRead[], path = "/skills") {
  const url = absoluteUrl(path);
  const siteUrl = absoluteUrl("/");
  return {
    "@context": "https://schema.org",
    "@graph": [
      breadcrumbJsonLd(
        [
          { name: siteConfig.name, url: siteUrl },
          { name: "Skills", url },
        ],
        `${url}#breadcrumb`,
      ),
      {
        "@id": `${url}#collection`,
        "@type": "CollectionPage",
        breadcrumb: { "@id": `${url}#breadcrumb` },
        description:
          "Browse reusable agent skills imported into Wardn Hub with source, category, install, and audit signals.",
        isPartOf: { "@id": `${siteUrl}#website` },
        mainEntity: {
          "@id": `${url}#item-list`,
          "@type": "ItemList",
          itemListElement: skills.map((skill, index) => ({
            "@type": "ListItem",
            item: skillWorkJsonLd(skill),
            position: index + 1,
          })),
          name: "Published agent skills",
          numberOfItems: skills.length,
        },
        name: "Agent skills",
        url,
      },
      {
        "@id": `${url}#dataset`,
        "@type": "Dataset",
        creator: { "@id": `${siteUrl}#organization` },
        description:
          "Wardn Hub public catalog dataset of reusable agent skills with source repositories, categories, installs, and audit metadata.",
        includedInDataCatalog: { "@id": `${siteUrl}#website` },
        keywords: ["agent skills", "AI agent workflows", "Codex skills", "Wardn Hub skills"],
        name: "Wardn Hub agent skills dataset",
        publisher: { "@id": `${siteUrl}#organization` },
        url,
        variableMeasured: [
          "skill name",
          "source repository",
          "category",
          "install count",
          "audit status",
          "audit score",
        ],
      },
    ],
  };
}

export function skillDetailJsonLd(params: {
  canonicalPath: string;
  filePath?: string;
  listing?: SkillRead;
  skill: SkillDetailResponse;
}) {
  const { listing, skill } = params;
  const url = absoluteUrl(params.canonicalPath);
  const skillUrl = absoluteUrl(skillDetailPathFromId(skill.id));
  const siteUrl = absoluteUrl("/");
  const sourceUrl = skill.sourceUrl ?? listing?.sourceUrl ?? "";
  const source = skill.source || listing?.source || "";
  const title = listing?.name || skill.slug;
  const filePath = params.filePath?.trim();
  const description =
    listing?.description ||
    "Reusable agent skill package published in Wardn Hub with source, bundle, file, and audit metadata.";
  const categories = skill.categories ?? listing?.categories ?? [];
  const skillNodeId = `${skillUrl}#skill`;
  const fileNodeId = filePath ? `${url}#file` : "";

  return {
    "@context": "https://schema.org",
    "@graph": [
      breadcrumbJsonLd(
        [
          { name: siteConfig.name, url: siteUrl },
          { name: "Skills", url: absoluteUrl("/skills") },
          ...(source
            ? [
                {
                  name: source.split("/", 1)[0] || source,
                  url: absoluteUrl(skillSourceOwnerPath(source)),
                },
                {
                  name: source.split("/")[1] || source,
                  url: absoluteUrl(skillSourcePathFromSource(source)),
                },
              ]
            : []),
          filePath ? { name: skill.slug, url: skillUrl } : { name: skill.slug, url },
          ...(filePath ? [{ name: filePath, url }] : []),
        ],
        `${url}#breadcrumb`,
      ),
      {
        "@id": `${url}#webpage`,
        "@type": "WebPage",
        breadcrumb: { "@id": `${url}#breadcrumb` },
        description,
        isPartOf: { "@id": `${siteUrl}#website` },
        mainEntity: { "@id": fileNodeId || skillNodeId },
        name: `${filePath || title} | ${siteConfig.name}`,
        url,
      },
      {
        "@id": skillNodeId,
        "@type": "CreativeWork",
        additionalProperty: [
          listing
            ? {
                "@type": "PropertyValue",
                name: "Install count",
                value: listing.installs,
              }
            : undefined,
          skill.hash
            ? {
                "@type": "PropertyValue",
                name: "Content hash",
                value: skill.hash,
              }
            : undefined,
          skill.resolutionStatus
            ? {
                "@type": "PropertyValue",
                name: "Package resolution status",
                value: skill.resolutionStatus,
              }
            : undefined,
        ],
        description,
        genre: categories.map((category) => category.name),
        identifier: skill.hash,
        isBasedOn: sourceUrl,
        keywords: uniqueStrings([
          "agent skill",
          "AI agent workflow",
          ...categories.map((category) => category.name),
        ]),
        name: title,
        url: skillUrl,
      },
      filePath
        ? {
            "@id": fileNodeId,
            "@type": "DigitalDocument",
            isPartOf: { "@id": skillNodeId },
            name: filePath,
            url,
          }
        : undefined,
    ],
  };
}

export function apiDocumentationJsonLd() {
  const url = absoluteUrl("/docs/api");
  const siteUrl = absoluteUrl("/");
  const title = "Wardn Hub API Documentation";
  return {
    "@context": "https://schema.org",
    "@graph": [
      breadcrumbJsonLd(
        [
          { name: siteConfig.name, url: siteUrl },
          { name: "API Documentation", url },
        ],
        `${url}#breadcrumb`,
      ),
      {
        "@id": `${url}#webpage`,
        "@type": "WebPage",
        breadcrumb: { "@id": `${url}#breadcrumb` },
        description:
          "Developer guide for the Wardn Hub API, including registry discovery, server detail, category, catalog, and submission endpoints.",
        isPartOf: { "@id": `${siteUrl}#website` },
        mainEntity: {
          "@type": "WebAPI",
          documentation: url,
          name: "Wardn Hub API",
          provider: { "@id": `${siteUrl}#organization` },
          url: absoluteUrl("/api/v1/docs"),
        },
        name: `${title} | ${siteConfig.name}`,
        url,
      },
    ],
  };
}
