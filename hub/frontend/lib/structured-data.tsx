import type {
  RegistryCategoryRead,
  RegistryServerDetailResponse,
  RegistryServerRead,
} from "@/lib/api/generated/model";
import { serverDetailPath } from "@/lib/public-registry";
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
  return {
    "@context": "https://schema.org",
    "@id": `${siteUrl}#website`,
    "@type": "WebSite",
    description: siteConfig.description,
    name: siteConfig.name,
    url: siteUrl,
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
        description: "Browse published Model Context Protocol server definitions by category on Wardn Hub.",
        isPartOf: { "@id": `${absoluteUrl("/")}#website` },
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
    ],
  };
}

export function registryIndexJsonLd(servers: RegistryServerRead[]) {
  const url = absoluteUrl("/");
  return {
    "@context": "https://schema.org",
    "@graph": [
      breadcrumbJsonLd([{ name: siteConfig.name, url }], `${url}#breadcrumb`),
      {
        "@id": `${url}#collection`,
        "@type": "CollectionPage",
        description: siteConfig.description,
        isPartOf: { "@id": `${url}#website` },
        mainEntity: {
          "@id": `${url}#item-list`,
          "@type": "ItemList",
          itemListElement: servers.map((server, index) => ({
            "@type": "ListItem",
            item: {
              "@id": `${absoluteUrl(serverDetailPath(server.name))}#server`,
              "@type": "SoftwareApplication",
              description: server.description,
              name: server.title || server.name,
              url: absoluteUrl(serverDetailPath(server.name)),
            },
            position: index + 1,
          })),
          name: "Published MCP servers",
          numberOfItems: servers.length,
        },
        name: siteConfig.name,
        url,
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
        description:
          params.category?.description ||
          `Published MCP server definitions in the ${params.categoryName} category on Wardn Hub.`,
        isPartOf: { "@id": `${absoluteUrl("/")}#website` },
        mainEntity: {
          "@id": `${url}#item-list`,
          "@type": "ItemList",
          itemListElement: params.servers.map((server, index) => ({
            "@type": "ListItem",
            item: {
              "@id": `${absoluteUrl(serverDetailPath(server.name))}#server`,
              "@type": "SoftwareApplication",
              description: server.description,
              name: server.title || server.name,
              url: absoluteUrl(serverDetailPath(server.name)),
            },
            position: index + 1,
          })),
          name: `${params.categoryName} MCP servers`,
          numberOfItems: params.servers.length,
        },
        name: `${params.categoryName} MCP servers`,
        url,
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
    softwareVersion: version,
    targetProduct: command ? [command, ...args].join(" ") : undefined,
  };
}

function remoteTargetJsonLd(remoteTarget: Record<string, unknown>, index: number) {
  return {
    "@type": "EntryPoint",
    contentType: stringValue(remoteTarget.type) || stringValue(remoteTarget.transport),
    name: stringValue(remoteTarget.name) || `Remote endpoint ${index + 1}`,
    urlTemplate: stringValue(remoteTarget.url),
  };
}

export function serverDetailJsonLd(detail: RegistryServerDetailResponse, canonicalPath: string) {
  const server = detail.server;
  const latestVersion =
    detail.versions?.find((version) => version.isLatest) ?? detail.versions?.[0];
  const repository = latestVersion?.repository ?? server.repository;
  const repositoryHref = repositoryUrl(repository);
  const documentation = latestVersion?.documentation || server.documentation || "";
  const documentationHref = urlValue(documentation);
  const websiteUrl = latestVersion?.websiteUrl || server.websiteUrl || "";
  const version = latestVersion?.version || server.latestVersion?.version || "";
  const packages = records(latestVersion?.packages);
  const remotes = records(latestVersion?.remotes);
  const categories = server.categories ?? [];
  const title = server.title || server.name;
  const url = absoluteUrl(canonicalPath);

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
        description: server.description,
        isPartOf: { "@id": `${absoluteUrl("/")}#website` },
        mainEntity: { "@id": `${url}#server` },
        name: `${title} | ${siteConfig.name}`,
        url,
      },
      {
        "@id": `${url}#server`,
        "@type": "SoftwareApplication",
        alternateName: server.name,
        applicationCategory: categories.map((category) => category.name),
        codeRepository: repositoryHref,
        description: server.description,
        hasPart: packages.map(packageTargetJsonLd),
        name: title,
        offers: remotes.map(remoteTargetJsonLd),
        sameAs: [repositoryHref, websiteUrl].filter(Boolean),
        softwareVersion: version,
        subjectOf: documentationHref
          ? { "@type": "CreativeWork", url: documentationHref }
          : undefined,
        url,
      },
    ],
  };
}
