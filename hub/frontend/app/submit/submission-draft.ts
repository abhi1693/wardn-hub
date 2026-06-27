import type {
  RegistryServerDetailResponse,
  RegistryServerVersionRead,
  SubmissionRead,
} from "@/lib/api/generated/model";

export const DEFAULT_SCHEMA =
  "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json";
export const PUBLISHER_META_KEY = "io.modelcontextprotocol.registry/publisher-provided";
export const SERVER_NAME_PATTERN = /^[a-zA-Z0-9.-]+\/[a-zA-Z0-9._-]+$/;
export const SERVER_VERSION_PATTERN =
  /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;

let generatedId = 0;

export type HeaderField = {
  id: string;
  name: string;
  description: string;
  required: boolean;
  secret: boolean;
};

export type EnvironmentField = HeaderField & {
  defaultValue: string;
  format: string;
};

export type PackageArgumentField = HeaderField & {
  defaultValue: string;
  flag: string;
  format: string;
  includeInLaunch: boolean;
  options: string;
  value: string;
  requiresValue: boolean;
};

export type RemoteTarget = {
  id: string;
  type: string;
  url: string;
  headers: HeaderField[];
  queryParameters: HeaderField[];
};

export type PackageTarget = {
  id: string;
  registryType: string;
  identifier: string;
  version: string;
  command: string;
  transportType: string;
  environmentVariables: EnvironmentField[];
  packageArguments: PackageArgumentField[];
};

export type SourceMode = "manual" | "repository";
export type SubmissionMode = "new" | "edit" | "new_version" | "server_edit" | "server_new_version";
export type PublishedServerDraftMode = "server_edit" | "server_new_version";

export type SubmissionDraftValues = {
  submissionMode: SubmissionMode;
  editingSubmissionId: string;
  editingSubmissionType: SubmissionRead["submissionType"];
  lockedServerName: string;
  lockedVersion: string;
  sourceMode: SourceMode;
  repositoryUrl: string;
  repositorySubfolder: string;
  name: string;
  isNameOverrideEnabled: boolean;
  title: string;
  version: string;
  description: string;
  documentation: string;
  websiteUrl: string;
  category: string;
  serverMeta: Record<string, unknown> | null;
  iconUrl: string;
  remotes: RemoteTarget[];
  packages: PackageTarget[];
  ownerOrganizationId: string;
  sourceImportMessage: string;
};

export const PACKAGE_RUNTIME_OPTIONS = [
  { value: "uvx", label: "UVX package" },
  { value: "npm", label: "NPM package" },
  { value: "pypi", label: "PyPI package" },
  { value: "oci", label: "OCI image" },
  { value: "docker", label: "Docker image" },
  { value: "mcpb", label: "MCPB package" },
];

export const GITHUB_REPOSITORY_SOURCE = "github";
export const GITHUB_HOST = "github.com";

export const TRANSPORT_OPTIONS = [
  { value: "stdio", label: "stdio" },
  { value: "streamable-http", label: "streamable-http" },
  { value: "sse", label: "sse" },
];

const SOURCE_REVIEW_FIELDS = [
  "filesRead",
  "installCommands",
  "commandArguments",
  "environmentVariables",
  "prerequisites",
  "capabilitiesReviewed",
  "limitationsReviewed",
  "unknowns",
];

export const PACKAGE_ARGUMENT_FORMAT_OPTIONS = [
  { value: "string", label: "Text" },
  { value: "boolean", label: "Toggle" },
  { value: "integer", label: "Number" },
  { value: "select", label: "Select" },
  { value: "file", label: "File" },
];

export function createId(prefix: string) {
  generatedId += 1;
  return `${prefix}-${generatedId}`;
}

export function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

export function booleanValue(value: unknown) {
  return value === true;
}

export function hasEnvironmentPlaceholder(value: string) {
  return value.includes("${") && value.includes("}");
}

export function splitPackageIdentifierVersion(value: string) {
  const trimmed = value.trim();
  const lastColon = trimmed.lastIndexOf(":");
  const lastSlash = trimmed.lastIndexOf("/");
  if (lastColon > lastSlash && lastColon < trimmed.length - 1) {
    return {
      identifier: trimmed.slice(0, lastColon),
      version: trimmed.slice(lastColon + 1),
    };
  }

  const equalityIndex = trimmed.indexOf("==");
  if (equalityIndex > 0 && equalityIndex < trimmed.length - 2) {
    return {
      identifier: trimmed.slice(0, equalityIndex),
      version: trimmed.slice(equalityIndex + 2),
    };
  }

  const atIndex = trimmed.lastIndexOf("@");
  if (atIndex > 0 && atIndex < trimmed.length - 1) {
    return {
      identifier: trimmed.slice(0, atIndex),
      version: trimmed.slice(atIndex + 1),
    };
  }

  return { identifier: value, version: "" };
}

export function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    : [];
}

export function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function hasSourceReviewEvidence(value: unknown) {
  const sourceReview = recordValue(value);
  if (!sourceReview) {
    return false;
  }

  if (SOURCE_REVIEW_FIELDS.some((field) => field in sourceReview)) {
    return true;
  }

  return Boolean(recordValue(sourceReview.human) || recordValue(sourceReview.llm));
}

export function emptyHeader(): HeaderField {
  return {
    id: createId("header"),
    name: "",
    description: "",
    required: false,
    secret: false,
  };
}

export function emptyEnvironment(): EnvironmentField {
  return {
    ...emptyHeader(),
    id: createId("env"),
    defaultValue: "",
    format: "string",
  };
}

export function emptyPackageArgument(): PackageArgumentField {
  return {
    ...emptyHeader(),
    id: createId("arg"),
    defaultValue: "",
    flag: "",
    format: "string",
    includeInLaunch: false,
    options: "",
    value: "",
    requiresValue: false,
  };
}

export function emptyRemote(): RemoteTarget {
  return {
    id: createId("remote"),
    type: "streamable-http",
    url: "",
    headers: [],
    queryParameters: [],
  };
}

export function emptyPackage(): PackageTarget {
  return {
    id: createId("package"),
    registryType: "npm",
    identifier: "",
    version: "",
    command: "",
    transportType: "stdio",
    environmentVariables: [],
    packageArguments: [],
  };
}

export function cleanPublisherPart(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/\.git$/i, "")
    .replace(/[^a-z0-9.-]+/g, "-")
    .replace(/^[.-]+|[.-]+$/g, "");
}

export function cleanNamePart(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/\.git$/i, "")
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^[._-]+|[._-]+$/g, "");
}

export function stripGitSuffix(value: string) {
  return value.trim().replace(/\.git$/i, "");
}

export function isGitHubHost(value: string) {
  return value.toLowerCase().replace(/^www\./, "") === GITHUB_HOST;
}

export function parseRepositoryReference(value: string) {
  const rawValue = value.trim();
  if (!rawValue) {
    return null;
  }

  const rawPathParts = rawValue
    .replace(/^\/+|\/+$/g, "")
    .split("/")
    .filter(Boolean);
  if (!rawValue.includes("://") && !rawValue.includes("@") && rawPathParts.length >= 2) {
    return {
      host: GITHUB_HOST,
      owner: rawPathParts[0],
      repo: stripGitSuffix(rawPathParts[1]),
    };
  }

  const sshMatch = rawValue.match(/^(?:git@|ssh:\/\/git@)([^/:]+)[:/]([^/]+)\/([^/?#]+)(?:[/?#].*)?$/i);
  if (sshMatch) {
    const host = sshMatch[1].toLowerCase().replace(/^www\./, "");
    if (!isGitHubHost(host)) {
      return null;
    }

    return {
      host,
      owner: sshMatch[2],
      repo: stripGitSuffix(sshMatch[3]),
    };
  }

  try {
    const url = new URL(rawValue.includes("://") ? rawValue : `https://${rawValue}`);
    const host = url.hostname.toLowerCase().replace(/^www\./, "");
    if (!isGitHubHost(host)) {
      return null;
    }
    const pathParts = url.pathname.split("/").filter(Boolean);
    if (pathParts.length < 2) {
      return null;
    }

    return {
      host,
      owner: pathParts[0],
      repo: stripGitSuffix(pathParts[1]),
    };
  } catch {
    if (rawPathParts.length < 2) {
      return null;
    }

    return {
      host: GITHUB_HOST,
      owner: rawPathParts[0],
      repo: stripGitSuffix(rawPathParts[1]),
    };
  }
}

export function repositoryPublisher(host: string, owner: string) {
  const ownerPart = cleanPublisherPart(owner);

  if (host === GITHUB_HOST) {
    return ownerPart ? `io.github.${ownerPart}` : "";
  }

  const hostPublisher = host
    .split(".")
    .reverse()
    .map(cleanPublisherPart)
    .filter(Boolean)
    .join(".");

  return [hostPublisher, ownerPart].filter(Boolean).join(".");
}

export function packagePublisher(registryType: string, identifier: string) {
  const runtime = cleanPublisherPart(registryType || "package");
  const trimmedIdentifier = identifier.trim();
  const scopedMatch = trimmedIdentifier.match(/^@([^/]+)\/(.+)$/);

  if (scopedMatch) {
    return {
      publisher: ["io", runtime, cleanPublisherPart(scopedMatch[1])].filter(Boolean).join("."),
      name: cleanNamePart(scopedMatch[2]),
    };
  }

  return {
    publisher: ["io", runtime].filter(Boolean).join("."),
    name: cleanNamePart(trimmedIdentifier),
  };
}

export function normalizeRepositoryReference(value: string) {
  return parseRepositorySource(value).repositoryUrl || value.trim();
}

export function repositorySourceSubfolder(value: string) {
  const rawValue = value.trim();
  if (!rawValue) {
    return "";
  }

  try {
    const url = new URL(rawValue.includes("://") ? rawValue : `https://${rawValue}`);
    const host = url.hostname.toLowerCase().replace(/^www\./, "");
    if (!isGitHubHost(host)) {
      return "";
    }
    const pathParts = url.pathname.replace(/^\/+|\/+$/g, "").split("/").filter(Boolean);
    const viewMode = pathParts[2];
    if (viewMode !== "tree" && viewMode !== "blob") {
      return "";
    }
    return pathParts.slice(4).join("/");
  } catch {
    const pathParts = rawValue.replace(/^\/+|\/+$/g, "").split("/").filter(Boolean);
    const viewMode = pathParts[2];
    if (viewMode !== "tree" && viewMode !== "blob") {
      return "";
    }
    return pathParts.slice(4).join("/");
  }
}

export function parseRepositorySource(value: string) {
  const repository = parseRepositoryReference(value);
  if (!repository) {
    return { repositoryUrl: value.trim(), subfolder: "" };
  }

  return {
    repositoryUrl: `${repository.owner}/${repository.repo}`,
    subfolder: repositorySourceSubfolder(value),
  };
}

export function repositoryWebUrl(value: string) {
  const repository = parseRepositoryReference(value);
  if (!repository) {
    return "";
  }

  return `https://${GITHUB_HOST}/${repository.owner}/${repository.repo}`;
}

export function generatedServerName(repositoryUrl: string, packages: PackageTarget[]) {
  const repository = parseRepositoryReference(repositoryUrl);
  if (repository) {
    const publisher = repositoryPublisher(repository.host, repository.owner);
    const serverName = cleanNamePart(repository.repo);
    if (publisher && serverName) {
      return `${publisher}/${serverName}`;
    }
  }

  const packageTarget = packages.find((item) => item.identifier.trim());
  if (packageTarget) {
    const generatedPackage = packagePublisher(packageTarget.registryType, packageTarget.identifier);
    if (generatedPackage.publisher && generatedPackage.name) {
      return `${generatedPackage.publisher}/${generatedPackage.name}`;
    }
  }

  return "";
}

export function initialHeaders(value: unknown): HeaderField[] {
  return records(value).map((header) => ({
    id: createId("header"),
    name: stringValue(header.name),
    description: stringValue(header.description),
    required: booleanValue(header.isRequired ?? header.required),
    secret: booleanValue(header.isSecret ?? header.secret),
  }));
}

export function initialEnvironment(value: unknown): EnvironmentField[] {
  return records(value).map((envVar) => ({
    id: createId("env"),
    name: stringValue(envVar.name),
    description: stringValue(envVar.description),
    defaultValue: stringValue(envVar.default),
    format: stringValue(envVar.format) || "string",
    required: booleanValue(envVar.isRequired),
    secret: booleanValue(envVar.isSecret),
  }));
}

export function initialTransportEnvironment(value: unknown): EnvironmentField[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.entries(value as Record<string, unknown>).map(([name, defaultValue]) => ({
    id: createId("env"),
    name,
    description: "",
    defaultValue: String(defaultValue ?? ""),
    format: "string",
    required: false,
    secret: /\b(TOKEN|SECRET|KEY|PASSWORD|CREDENTIAL)\b/i.test(name),
  }));
}

export function mergeEnvironmentFields(environmentVariables: EnvironmentField[]) {
  const merged = new Map<string, EnvironmentField>();

  for (const envVar of environmentVariables) {
    const name = envVar.name.trim();
    if (!name) {
      merged.set(envVar.id, envVar);
      continue;
    }

    const existing = merged.get(name);
    if (!existing) {
      merged.set(name, { ...envVar, name });
      continue;
    }

    merged.set(name, {
      ...existing,
      description: existing.description || envVar.description,
      defaultValue: existing.defaultValue || envVar.defaultValue,
      format: existing.format || envVar.format || "string",
      required: existing.required || envVar.required,
      secret: existing.secret || envVar.secret,
    });
  }

  return [...merged.values()];
}

export function duplicateEnvironmentNames(environmentVariables: EnvironmentField[]) {
  const seen = new Set<string>();
  const duplicates = new Set<string>();

  for (const envVar of environmentVariables) {
    const name = envVar.name.trim();
    if (!name) continue;
    if (seen.has(name)) duplicates.add(name);
    seen.add(name);
  }

  return [...duplicates].sort();
}

export function splitArgumentFlagRequiresValue(flag: string, fallbackRequiresValue = false) {
  const trimmed = flag.trim();
  const match = trimmed.match(/^(.*?)(?:\s*(?:=\s*)?<([^<>]+)>|\s+\[([^\[\]]+)\])$/);
  if (!match) {
    return { flag: trimmed, requiresValue: fallbackRequiresValue };
  }

  return {
    flag: match[1].trim(),
    requiresValue: true,
  };
}

export function normalizeArgumentStaticValue(value: string) {
  const trimmed = value.trim();
  if (/^(?:<[^<>]+>|\[[^\[\]]+\])$/.test(trimmed)) {
    return { value: "", requiresValue: true };
  }
  return { value, requiresValue: false };
}

export function initialPackageArguments(value: unknown): PackageArgumentField[] {
  return records(value).map((argument) => {
    const parsedFlag = splitArgumentFlagRequiresValue(
      stringValue(argument.flag),
      booleanValue(argument.requiresValue ?? argument.requires_value),
    );
    return {
      id: createId("arg"),
      name: stringValue(argument.name),
      description: stringValue(argument.description),
      defaultValue: stringValue(argument.default),
      flag: parsedFlag.flag,
      format: stringValue(argument.format) || "string",
      includeInLaunch: booleanValue(
        argument.includeInLaunch ?? argument.includeInCommand ?? argument.include_in_launch,
      ),
      options: Array.isArray(argument.options) ? argument.options.map(String).join(", ") : "",
      required: booleanValue(argument.isRequired),
      secret: booleanValue(argument.isSecret),
      value: stringValue(argument.value),
      requiresValue: parsedFlag.requiresValue,
    };
  });
}

export function initialTransportArguments(value: unknown): PackageArgumentField[] {
  if (!Array.isArray(value)) return [];
  return value.map((argument, index) => ({
    id: createId("arg"),
    name: "",
    description: "",
    defaultValue: "",
    flag: "",
    format: "string",
    includeInLaunch: true,
    options: "",
    required: index === 0,
    secret: false,
    value: String(argument),
    requiresValue: false,
  }));
}

export function importedRemotes(value: unknown): RemoteTarget[] {
  return records(value).map((remote) => ({
    id: createId("remote"),
    type: stringValue(remote.type) || "streamable-http",
    url: stringValue(remote.url),
    headers: initialHeaders(remote.headers),
    queryParameters: initialHeaders(remote.queryParameters ?? remote.queryParams),
  }));
}

export function importedPackages(value: unknown): PackageTarget[] {
  return records(value).map((packageTarget) => {
    const transport = packageTarget.transport as Record<string, unknown> | undefined;
    const parsedPackage = splitPackageIdentifierVersion(stringValue(packageTarget.identifier));
    const importedVersion = stringValue(packageTarget.version).replaceAll("$VERSION", "latest");
    return {
      id: createId("package"),
      registryType: stringValue(packageTarget.registryType) || "npm",
      identifier: parsedPackage.identifier.replaceAll("$VERSION", "latest"),
      version: importedVersion || parsedPackage.version.replaceAll("$VERSION", "latest"),
      command: stringValue(transport?.command),
      transportType: stringValue(transport?.type) || "stdio",
      environmentVariables: mergeEnvironmentFields([
        ...initialTransportEnvironment(transport?.env),
        ...initialEnvironment(packageTarget.environmentVariables),
      ]),
      packageArguments: [
        ...initialTransportArguments(transport?.args),
        ...initialPackageArguments(packageTarget.packageArguments),
      ],
    };
  });
}

export function firstIconUrl(value: unknown) {
  const icon = records(value)[0];
  return stringValue(icon?.src);
}

export function categoryFromServerJson(value: Record<string, unknown>) {
  const meta = recordValue(value._meta);
  if (!meta) {
    return "";
  }

  const publisherMeta = recordValue(meta[PUBLISHER_META_KEY]);
  const publisherCategory = stringValue(publisherMeta?.category);
  if (publisherCategory) {
    return publisherCategory;
  }

  const publisherCategories = Array.isArray(publisherMeta?.categories)
    ? publisherMeta.categories
    : [];
  const firstPublisherCategory = publisherCategories.find(
    (item): item is string => typeof item === "string" && Boolean(item.trim()),
  );
  if (firstPublisherCategory) {
    return firstPublisherCategory;
  }

  const category = stringValue(meta.category);
  if (category) {
    return category;
  }

  const categories = Array.isArray(meta.categories) ? meta.categories : [];
  return categories.find(
    (item): item is string => typeof item === "string" && Boolean(item.trim()),
  ) ?? "";
}

function uniqueNonEmptyValues(values: string[]) {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

export function humanSourceReviewPayload({
  sourceMode,
  repositoryUrl,
  repositorySubfolder,
  websiteUrl,
  documentation,
  packages,
  sourceImportMessage,
}: {
  sourceMode: SourceMode;
  repositoryUrl: string;
  repositorySubfolder: string;
  websiteUrl: string;
  documentation: string;
  packages: PackageTarget[];
  sourceImportMessage: string;
}) {
  const repositoryReference = normalizeRepositoryReference(repositoryUrl);
  const filesRead = uniqueNonEmptyValues([
    sourceMode === "repository" && repositoryReference
      ? `${repositoryReference}${repositorySubfolder.trim() ? `/${repositorySubfolder.trim()}` : ""}`
      : "",
    documentation.trim() ? "README.md" : "",
    sourceImportMessage === "Registry document loaded." ? "server.json" : "",
    sourceImportMessage === "MCP client configuration loaded." ? "mcp.json" : "",
    websiteUrl.trim(),
    !repositoryReference && !documentation.trim() && !websiteUrl.trim()
      ? "Wardn Hub submission form"
      : "",
  ]);
  const installCommands = uniqueNonEmptyValues(
    packages.flatMap((packageTarget) => {
      const command = packageTarget.command.trim();
      const launchArgs = launchArgumentValues(packageTarget.packageArguments);
      if (command) {
        return [[command, ...launchArgs].join(" ")];
      }
      return packageTarget.identifier.trim() ? [packageTarget.identifier.trim()] : [];
    }),
  );
  const commandArguments = uniqueNonEmptyValues(
    packages.flatMap((packageTarget) => {
      const launchArgs = launchArgumentValues(packageTarget.packageArguments);
      const documentedArgs = packageTarget.packageArguments.flatMap((argument) => {
        const value = argument.value.trim();
        const flag = argument.flag.trim();
        const name = argument.name.trim();
        const defaultValue = argument.defaultValue.trim();
        if (value) return [value];
        if (flag && defaultValue) return [`${flag} ${defaultValue}`];
        if (flag) return [flag];
        if (name) return [name];
        return [];
      });
      const values = [...launchArgs, ...documentedArgs];
      if (values.length > 0) {
        return values;
      }
      return packageTarget.identifier.trim()
        ? [`No configurable command arguments documented for ${packageTarget.identifier.trim()}.`]
        : [];
    }),
  );

  return {
    filesRead,
    installCommands,
    commandArguments,
    environmentVariables: packages.flatMap((packageTarget) =>
      publicEnvironment(packageTarget.environmentVariables),
    ),
    prerequisites: [],
    capabilitiesReviewed: true,
    limitationsReviewed: true,
    unknowns: [],
  };
}

export function serverMetaPayload(
  existingMeta: Record<string, unknown> | null,
  category: string,
  humanSourceReview?: Record<string, unknown>,
) {
  const meta = existingMeta ? { ...existingMeta } : {};
  if (category) {
    const publisherMeta = recordValue(meta[PUBLISHER_META_KEY]);
    meta[PUBLISHER_META_KEY] = {
      ...(publisherMeta ?? {}),
      category,
    };
  }

  if (humanSourceReview && !hasSourceReviewEvidence(meta.sourceReview)) {
    meta.sourceReview = { human: humanSourceReview };
  }

  return Object.keys(meta).length > 0 ? meta : undefined;
}

export function bumpPatchVersion(value: string) {
  const match = value.match(/^(\d+)\.(\d+)\.(\d+)$/);
  if (!match) {
    return value;
  }

  return `${match[1]}.${match[2]}.${Number(match[3]) + 1}`;
}

export function publicHeaders(headers: HeaderField[]) {
  return headers
    .filter((header) => header.name.trim())
    .map((header) => ({
      name: header.name.trim(),
      description: header.description.trim(),
      isRequired: header.required,
      isSecret: header.secret,
    }));
}

export function publicQueryParameters(queryParameters: HeaderField[]) {
  return queryParameters
    .filter((parameter) => parameter.name.trim())
    .map((parameter) => ({
      name: parameter.name.trim(),
      description: parameter.description.trim(),
      isRequired: parameter.required,
      isSecret: parameter.secret,
    }));
}

export function publicEnvironment(environmentVariables: EnvironmentField[]) {
  return environmentVariables
    .filter((envVar) => envVar.name.trim())
    .map((envVar) => ({
      name: envVar.name.trim(),
      description: envVar.description.trim(),
      default: envVar.defaultValue.trim(),
      isRequired: envVar.required,
      isSecret: envVar.secret,
      format: envVar.format || "string",
    }));
}

export function publicPackageArguments(packageArguments: PackageArgumentField[]): Record<string, unknown>[] {
  return packageArguments
    .map((argument): Record<string, unknown> | null => {
      const name = argument.name.trim();
      const value = argument.value.trim();
      const description = argument.description.trim();
      if (!name && value) {
        return {
          value,
          description,
          includeInLaunch: argument.includeInLaunch,
        };
      }
      if (!name) {
        return null;
      }
      const options = argument.options
        .split(",")
        .map((option) => option.trim())
        .filter(Boolean);

      return {
        name,
        flag: argument.flag.trim(),
        value: value,
        requiresValue: argument.requiresValue,
        description,
        default: argument.defaultValue.trim(),
        format: argument.format || "string",
        includeInLaunch: argument.includeInLaunch,
        options,
        isRequired: argument.required,
        isSecret: argument.secret,
      };
    })
    .filter((argument): argument is Record<string, unknown> => Boolean(argument));
}

export function launchArgumentValues(packageArguments: PackageArgumentField[]) {
  return packageArguments
    .filter((argument) => argument.includeInLaunch)
    .flatMap((argument) => {
      const value = argument.value.trim();
      if (value) return [value];

      const flag = argument.flag.trim();
      if (!flag) return [];

      const defaultValue = argument.defaultValue.trim();
      if (defaultValue) return [flag, defaultValue];

      return [flag];
    });
}

function serverJsonRecord(value: unknown): Record<string, unknown> {
  return recordValue(value) ?? {};
}

function repositoryRecord(serverJson: Record<string, unknown>): Record<string, unknown> | null {
  return recordValue(serverJson.repository);
}

function serverJsonDraftValues(serverJson: Record<string, unknown>) {
  const repository = repositoryRecord(serverJson);
  const repositoryReference = normalizeRepositoryReference(stringValue(repository?.url));
  const icons = records(serverJson.icons);

  return {
    sourceMode: repositoryReference ? "repository" : "manual",
    repositoryUrl: repositoryReference,
    repositorySubfolder: stringValue(repository?.subfolder),
    title: stringValue(serverJson.title),
    description: stringValue(serverJson.description),
    documentation: stringValue(serverJson.documentation),
    websiteUrl: stringValue(serverJson.websiteUrl),
    category: categoryFromServerJson(serverJson),
    serverMeta: recordValue(serverJson._meta),
    iconUrl: firstIconUrl(icons),
    remotes: importedRemotes(serverJson.remotes),
    packages: importedPackages(serverJson.packages),
  } satisfies Pick<
    SubmissionDraftValues,
    | "sourceMode"
    | "repositoryUrl"
    | "repositorySubfolder"
    | "title"
    | "description"
    | "documentation"
    | "websiteUrl"
    | "category"
    | "serverMeta"
    | "iconUrl"
    | "remotes"
    | "packages"
  >;
}

export function submissionDraftValues(
  submission: SubmissionRead,
  mode: SubmissionMode,
): SubmissionDraftValues {
  const serverJson = serverJsonRecord(submission.serverJson);
  const draft = serverJsonDraftValues(serverJson);

  return {
    ...draft,
    submissionMode: mode,
    editingSubmissionId: mode === "edit" ? submission.id : "",
    editingSubmissionType: mode === "new_version" ? "new_version" : submission.submissionType,
    lockedServerName: mode === "new_version" ? submission.name : "",
    lockedVersion: "",
    name: submission.name,
    isNameOverrideEnabled: true,
    version: mode === "new_version" ? bumpPatchVersion(submission.version) : submission.version,
    ownerOrganizationId: submission.ownerOrganizationId ?? "",
    sourceImportMessage:
      mode === "new_version"
        ? "Published server loaded. Update the version before submitting."
        : "Submission loaded for editing.",
  };
}

export function publishedServerDraftValues(
  response: RegistryServerDetailResponse,
  version: RegistryServerVersionRead,
  mode: PublishedServerDraftMode,
): SubmissionDraftValues {
  const serverJson = serverJsonRecord(version.serverJson);
  const draft = serverJsonDraftValues(serverJson);

  return {
    ...draft,
    submissionMode: mode,
    editingSubmissionId: "",
    editingSubmissionType: "new_server",
    lockedServerName: response.server.name,
    lockedVersion: mode === "server_edit" ? version.version : "",
    name: response.server.name,
    isNameOverrideEnabled: true,
    title: draft.title || response.server.title,
    version: mode === "server_new_version" ? bumpPatchVersion(version.version) : version.version,
    description: draft.description || response.server.description,
    documentation: draft.documentation || response.server.documentation || "",
    websiteUrl: draft.websiteUrl || response.server.websiteUrl || "",
    ownerOrganizationId: response.server.organization?.id ?? "",
    sourceImportMessage:
      mode === "server_new_version"
        ? "Published server loaded. Update the version before publishing."
        : "Published server loaded for editing.",
  };
}
