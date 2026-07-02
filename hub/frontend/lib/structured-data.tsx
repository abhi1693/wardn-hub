import type {
  RegistryCategoryRead,
  RegistryServerDetailResponse,
  RegistryServerRead,
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
        description: "Browse community-curated Model Context Protocol servers by category on Wardn Hub.",
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
      {
        "@id": `${url}#dataset`,
        "@type": "Dataset",
        description:
          "Wardn Hub category index for discovering Model Context Protocol servers by use case.",
        includedInDataCatalog: { "@id": `${absoluteUrl("/")}#website` },
        keywords: ["Model Context Protocol", "MCP servers", "MCP categories"],
        name: "Wardn Hub MCP server category dataset",
        url,
        variableMeasured: ["category", "description", "sort order"],
      },
    ],
  };
}

export function registryIndexJsonLd(servers: RegistryServerRead[]) {
  const url = absoluteUrl("/");
  const dateModified = newestDate(servers.map((server) => server.updatedAt));
  return {
    "@context": "https://schema.org",
    "@graph": [
      breadcrumbJsonLd([{ name: siteConfig.name, url }], `${url}#breadcrumb`),
      {
        "@id": `${url}#collection`,
        "@type": "CollectionPage",
        dateModified,
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
      {
        "@id": `${url}#dataset`,
        "@type": "Dataset",
        dateModified,
        description:
          "Wardn Hub public catalog dataset of published Model Context Protocol servers, packages, remotes, categories, and trust signals.",
        includedInDataCatalog: { "@id": `${url}#website` },
        keywords: ["Model Context Protocol", "MCP registry", "MCP servers", "AI tools"],
        name: "Wardn Hub published MCP server dataset",
        url,
        variableMeasured: [
          "server name",
          "description",
          "category",
          "package target",
          "remote endpoint",
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
      {
        "@id": `${url}#dataset`,
        "@type": "Dataset",
        dateModified,
        description:
          params.category?.description ||
          `Wardn Hub dataset of published ${params.categoryName} MCP servers.`,
        includedInDataCatalog: { "@id": `${absoluteUrl("/")}#website` },
        keywords: ["Model Context Protocol", "MCP servers", params.categoryName],
        name: `${params.categoryName} MCP server dataset`,
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

function targetValue(item: Record<string, unknown>, fallback: string) {
  return (
    stringValue(item.identifier) ||
    stringValue(item.url) ||
    stringValue(item.name) ||
    stringValue(item.package) ||
    fallback
  );
}

function transportCommand(packageTarget: Record<string, unknown>) {
  const transport = recordValue(packageTarget.transport);
  const command = stringValue(transport.command);
  const args = Array.isArray(transport.args) ? transport.args.map(String).filter(Boolean) : [];
  const identifier = targetValue(packageTarget, "");
  if (!command) return "";
  if (args.length > 0) return [command, ...args].join(" ");
  if (identifier && ["npx", "uvx", "pipx"].includes(command.toLowerCase())) {
    return `${command} ${identifier}`;
  }
  return command;
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
    ...packages.map((packageTarget) => stringValue(recordValue(packageTarget.transport).type) || "stdio"),
    ...remotes.map((remoteTarget) => stringValue(remoteTarget.type) || "remote"),
  ]);
}

function sentenceList(values: string[], emptyLabel: string, limit = 4) {
  if (values.length === 0) return emptyLabel;
  const visible = values.slice(0, limit).join(", ");
  const remaining = values.length - limit;
  return remaining > 0 ? `${visible}, and ${remaining} more` : visible;
}

function serverFaqJsonLd(params: {
  commands: string[];
  description?: string;
  environmentVariables: string[];
  repositoryHref: string;
  title: string;
  transports: string[];
  url: string;
}) {
  const description =
    params.description ||
    `${params.title} is listed in Wardn Hub with package, transport, configuration, and trust metadata.`;

  return {
    "@id": `${params.url}#faq`,
    "@type": "FAQPage",
    mainEntity: [
      {
        "@type": "Question",
        acceptedAnswer: {
          "@type": "Answer",
          text: `${params.title} is a Model Context Protocol server. ${description}`,
        },
        name: `What is ${params.title}?`,
      },
      {
        "@type": "Question",
        acceptedAnswer: {
          "@type": "Answer",
          text:
            params.commands.length > 0
              ? `Install or launch ${params.title} with ${sentenceList(params.commands, "the published package target")}.`
              : `Wardn Hub does not list a package launch command for ${params.title}; check the upstream documentation before installing.`,
        },
        name: `How do I install ${params.title}?`,
      },
      {
        "@type": "Question",
        acceptedAnswer: {
          "@type": "Answer",
          text:
            params.environmentVariables.length > 0
              ? `${params.title} lists these environment variables: ${sentenceList(params.environmentVariables, "none", 8)}.`
              : `${params.title} does not list required environment variables in the published registry metadata.`,
        },
        name: `What environment variables does ${params.title} use?`,
      },
      {
        "@type": "Question",
        acceptedAnswer: {
          "@type": "Answer",
          text:
            params.transports.length > 0
              ? `${params.title} is listed with ${sentenceList(params.transports, "no listed transports")} transport support.`
              : `${params.title} does not have a listed transport in Wardn Hub metadata.`,
        },
        name: `Which transports does ${params.title} support?`,
      },
      {
        "@type": "Question",
        acceptedAnswer: {
          "@type": "Answer",
          text: params.repositoryHref
            ? `Verify ${params.title} against its upstream source at ${params.repositoryHref}.`
            : `Verify ${params.title} against upstream documentation before installation or runtime use.`,
        },
        name: `Where can I verify ${params.title}?`,
      },
    ],
  };
}

function serverInstallHowToJsonLd(params: {
  command: string;
  repositoryHref: string;
  title: string;
  url: string;
}) {
  if (!params.command) return null;
  return {
    "@id": `${params.url}#install-how-to`,
    "@type": "HowTo",
    description: `Install or launch ${params.title} from the package transport listed by Wardn Hub.`,
    mainEntityOfPage: { "@id": `${params.url}#webpage` },
    name: `How to install ${params.title}`,
    step: [
      {
        "@type": "HowToStep",
        name: "Review upstream documentation",
        position: 1,
        text: params.repositoryHref
          ? `Open the upstream source at ${params.repositoryHref} and confirm the current installation instructions.`
          : "Open the upstream documentation and confirm the current installation instructions.",
      },
      {
        "@type": "HowToStep",
        name: "Run the documented command",
        position: 2,
        text: `Use the listed launch command: ${params.command}`,
      },
      {
        "@type": "HowToStep",
        name: "Configure required settings",
        position: 3,
        text: "Set any documented environment variables or command arguments before connecting an MCP client.",
      },
    ],
    tool: params.command,
    url: params.url,
  };
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
  const packageTransportCommands = uniqueStrings(packages.map(transportCommand));
  const commands = uniqueStrings([
    ...reviewListValues(sourceReview.installCommands),
    ...packageTransportCommands,
  ]);
  const environmentVariables = environmentVariableNames(packages, remotes, sourceReview);
  const commandArguments = commandArgumentNames(packages, sourceReview);
  const transports = transportNames(packages, remotes);
  const categories = server.categories ?? [];
  const title = server.title || server.name;
  const registryNamespace = server.registryNamespace;
  const url = absoluteUrl(canonicalPath);
  const dateModified = dateValue(latestVersion?.updatedAt) || dateValue(server.updatedAt);
  const howTo = serverInstallHowToJsonLd({
    command: packageTransportCommands[0] ?? "",
    repositoryHref,
    title,
    url,
  });

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
        isPartOf: { "@id": `${absoluteUrl("/")}#website` },
        mainEntity: { "@id": `${url}#server` },
        name: `${title} | ${siteConfig.name}`,
        url,
      },
      {
        "@id": `${url}#server`,
        "@type": "SoftwareApplication",
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
        ],
        alternateName: server.name,
        applicationCategory: categories.map((category) => category.name),
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
        offers: remotes.map(remoteTargetJsonLd),
        sameAs: [repositoryHref, websiteUrl].filter(Boolean),
        softwareVersion: version,
        subjectOf: documentationHref
          ? { "@type": "CreativeWork", url: documentationHref }
          : undefined,
        url,
      },
      serverFaqJsonLd({
        commands,
        description: server.description,
        environmentVariables,
        repositoryHref,
        title,
        transports,
        url,
      }),
      howTo,
    ],
  };
}
