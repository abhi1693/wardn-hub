"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ClipboardEvent, FormEvent } from "react";
import { useEffect, useState } from "react";
import { ArrowLeft, Database, Plus, Save, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  HubApiError,
  createSubmission,
  currentUser,
  listCategories,
  submissionAction,
} from "@/lib/api/hub";
import type { RegistryCategoryRead, UserRead } from "@/lib/api/generated/model";

const DEFAULT_SCHEMA =
  "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json";
const PUBLISHER_META_KEY = "io.modelcontextprotocol.registry/publisher-provided";
const SERVER_NAME_PATTERN = /^[a-zA-Z0-9.-]+\/[a-zA-Z0-9._-]+$/;
const SERVER_VERSION_PATTERN =
  /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;

let generatedId = 0;

type HeaderField = {
  id: string;
  name: string;
  description: string;
  required: boolean;
  secret: boolean;
};

type EnvironmentField = HeaderField & {
  defaultValue: string;
  format: string;
};

type PackageArgumentField = HeaderField & {
  defaultValue: string;
  flag: string;
  format: string;
  options: string;
  value: string;
};

type RemoteTarget = {
  id: string;
  type: string;
  url: string;
  headers: HeaderField[];
};

type PackageTarget = {
  id: string;
  registryType: string;
  identifier: string;
  version: string;
  transportType: string;
  environmentVariables: EnvironmentField[];
  packageArguments: PackageArgumentField[];
};

type SourceMode = "manual" | "repository";

type SourceMetadata = {
  source?: string;
  name?: string;
  title?: string;
  description?: string;
  documentation?: string;
  version?: string;
  websiteUrl?: string;
  repository?: {
    source?: string;
    url?: string;
    subfolder?: string;
  };
  iconUrl?: string;
  icons?: unknown;
  remotes?: unknown;
  packages?: unknown;
};

type GitHubRepositoryMetadata = {
  name?: unknown;
  description?: unknown;
  homepage?: unknown;
  html_url?: unknown;
  owner?: {
    avatar_url?: unknown;
  };
};

const PACKAGE_RUNTIME_OPTIONS = [
  { value: "uvx", label: "UVX package" },
  { value: "npm", label: "NPM package" },
  { value: "pypi", label: "PyPI package" },
  { value: "oci", label: "OCI image" },
  { value: "docker", label: "Docker image" },
  { value: "mcpb", label: "MCPB package" },
];

const GITHUB_REPOSITORY_SOURCE = "github";
const GITHUB_HOST = "github.com";

const TRANSPORT_OPTIONS = [
  { value: "stdio", label: "stdio" },
  { value: "streamable-http", label: "streamable-http" },
  { value: "sse", label: "sse" },
];

const PACKAGE_ARGUMENT_FORMAT_OPTIONS = [
  { value: "string", label: "Text" },
  { value: "boolean", label: "Toggle" },
  { value: "integer", label: "Number" },
  { value: "select", label: "Select" },
  { value: "file", label: "File" },
];

function createId(prefix: string) {
  generatedId += 1;
  return `${prefix}-${generatedId}`;
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function booleanValue(value: unknown) {
  return value === true;
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    : [];
}

function emptyHeader(): HeaderField {
  return {
    id: createId("header"),
    name: "",
    description: "",
    required: false,
    secret: false,
  };
}

function emptyEnvironment(): EnvironmentField {
  return {
    ...emptyHeader(),
    id: createId("env"),
    defaultValue: "",
    format: "string",
  };
}

function emptyPackageArgument(): PackageArgumentField {
  return {
    ...emptyHeader(),
    id: createId("arg"),
    defaultValue: "",
    flag: "",
    format: "string",
    options: "",
    value: "",
  };
}

function emptyRemote(): RemoteTarget {
  return {
    id: createId("remote"),
    type: "streamable-http",
    url: "",
    headers: [],
  };
}

function emptyPackage(): PackageTarget {
  return {
    id: createId("package"),
    registryType: "npm",
    identifier: "",
    version: "",
    transportType: "stdio",
    environmentVariables: [],
    packageArguments: [],
  };
}

function cleanPublisherPart(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/\.git$/i, "")
    .replace(/[^a-z0-9.-]+/g, "-")
    .replace(/^[.-]+|[.-]+$/g, "");
}

function cleanNamePart(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/\.git$/i, "")
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^[._-]+|[._-]+$/g, "");
}

function stripGitSuffix(value: string) {
  return value.trim().replace(/\.git$/i, "");
}

function isGitHubHost(value: string) {
  return value.toLowerCase().replace(/^www\./, "") === GITHUB_HOST;
}

function parseRepositoryReference(value: string) {
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

function repositoryPublisher(host: string, owner: string) {
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

function packagePublisher(registryType: string, identifier: string) {
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

function normalizeRepositoryReference(value: string) {
  const repository = parseRepositoryReference(value);
  if (!repository) {
    return value.trim();
  }

  return `${repository.owner}/${repository.repo}`;
}

function repositoryWebUrl(value: string) {
  const repository = parseRepositoryReference(value);
  if (!repository) {
    return "";
  }

  return `https://${GITHUB_HOST}/${repository.owner}/${repository.repo}`;
}

async function fetchGitHubRepositoryMetadata(repositoryReference: string): Promise<SourceMetadata> {
  const repository = parseRepositoryReference(repositoryReference);
  if (!repository) {
    return {};
  }

  try {
    const response = await fetch(
      `https://api.github.com/repos/${encodeURIComponent(repository.owner)}/${encodeURIComponent(repository.repo)}`,
      {
        cache: "no-store",
        headers: {
          Accept: "application/vnd.github+json",
        },
      },
    );
    if (!response.ok) {
      return {};
    }

    const payload = (await response.json()) as GitHubRepositoryMetadata;
    const homepage = stringValue(payload.homepage);
    const htmlUrl = stringValue(payload.html_url);

    return {
      title: stringValue(payload.name),
      description: stringValue(payload.description),
      iconUrl: stringValue(payload.owner?.avatar_url),
      websiteUrl: homepage || htmlUrl,
    };
  } catch {
    return {};
  }
}

async function fetchGitHubReadmeDocumentation(
  repositoryReference: string,
  subfolder: string,
): Promise<SourceMetadata> {
  const repository = parseRepositoryReference(repositoryReference);
  if (!repository) {
    return {};
  }

  const folder = subfolder.trim().replace(/^\/+|\/+$/g, "");
  const readmePath = folder
    ? `/${folder.split("/").map(encodeURIComponent).join("/")}`
    : "";

  try {
    const response = await fetch(
      `https://api.github.com/repos/${encodeURIComponent(repository.owner)}/${encodeURIComponent(repository.repo)}/readme${readmePath}`,
      {
        cache: "no-store",
        headers: {
          Accept: "application/vnd.github.raw",
        },
      },
    );
    if (!response.ok) {
      return {};
    }

    return { documentation: await response.text() };
  } catch {
    return {};
  }
}

function metadataWithFallback(metadata: SourceMetadata, fallback: SourceMetadata): SourceMetadata {
  return {
    ...metadata,
    title: metadata.title || fallback.title,
    description: metadata.description || fallback.description,
    documentation: metadata.documentation || fallback.documentation,
    iconUrl: metadata.iconUrl || fallback.iconUrl,
    websiteUrl: metadata.websiteUrl || fallback.websiteUrl,
  };
}

function generatedServerName(repositoryUrl: string, packages: PackageTarget[]) {
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

function initialHeaders(value: unknown): HeaderField[] {
  return records(value).map((header) => ({
    id: createId("header"),
    name: stringValue(header.name),
    description: stringValue(header.description),
    required: booleanValue(header.isRequired),
    secret: booleanValue(header.isSecret),
  }));
}

function initialEnvironment(value: unknown): EnvironmentField[] {
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

function initialPackageArguments(value: unknown): PackageArgumentField[] {
  return records(value).map((argument) => ({
    id: createId("arg"),
    name: stringValue(argument.name),
    description: stringValue(argument.description),
    defaultValue: stringValue(argument.default),
    flag: stringValue(argument.flag),
    format: stringValue(argument.format) || "string",
    options: Array.isArray(argument.options) ? argument.options.map(String).join(", ") : "",
    required: booleanValue(argument.isRequired),
    secret: booleanValue(argument.isSecret),
    value: stringValue(argument.value),
  }));
}

function importedRemotes(value: unknown): RemoteTarget[] {
  return records(value).map((remote) => ({
    id: createId("remote"),
    type: stringValue(remote.type) || "streamable-http",
    url: stringValue(remote.url),
    headers: initialHeaders(remote.headers),
  }));
}

function importedPackages(value: unknown): PackageTarget[] {
  return records(value).map((packageTarget) => {
    const transport = packageTarget.transport as Record<string, unknown> | undefined;
    return {
      id: createId("package"),
      registryType: stringValue(packageTarget.registryType) || "npm",
      identifier: stringValue(packageTarget.identifier).replaceAll("$VERSION", "latest"),
      version: stringValue(packageTarget.version).replaceAll("$VERSION", "latest"),
      transportType: stringValue(transport?.type) || "stdio",
      environmentVariables: initialEnvironment(packageTarget.environmentVariables),
      packageArguments: initialPackageArguments(packageTarget.packageArguments),
    };
  });
}

function firstIconUrl(value: unknown) {
  const icon = records(value)[0];
  return stringValue(icon?.src);
}

function publicHeaders(headers: HeaderField[]) {
  return headers
    .filter((header) => header.name.trim())
    .map((header) => ({
      name: header.name.trim(),
      description: header.description.trim(),
      isRequired: header.required,
      isSecret: header.secret,
    }));
}

function publicEnvironment(environmentVariables: EnvironmentField[]) {
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

function publicPackageArguments(packageArguments: PackageArgumentField[]): Record<string, unknown>[] {
  return packageArguments
    .map((argument): Record<string, unknown> | null => {
      const name = argument.name.trim();
      const value = argument.value.trim();
      const description = argument.description.trim();
      if (!name && value) {
        return { value, description };
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
        description,
        default: argument.defaultValue.trim(),
        format: argument.format || "string",
        options,
        isRequired: argument.required,
        isSecret: argument.secret,
      };
    })
    .filter((argument): argument is Record<string, unknown> => Boolean(argument));
}

function githubRawCandidates(repositoryReference: string, subfolder: string) {
  const repository = parseRepositoryReference(repositoryReference);
  if (!repository) {
    return [];
  }

  const folder = subfolder.trim().replace(/^\/+|\/+$/g, "");
  const paths = ["server.json", "mcp.json"];
  const branches = ["main", "master"];

  return branches.flatMap((branch) =>
    paths.map((path) => {
      const filePath = [folder, path].filter(Boolean).join("/");
      return `https://raw.githubusercontent.com/${repository.owner}/${repository.repo}/${branch}/${filePath}`;
    }),
  );
}

function metadataFromMcpJson(
  value: Record<string, unknown>,
  repositoryReference: string,
): SourceMetadata {
  const servers = value.mcpServers as Record<string, unknown> | undefined;
  const [serverTitle, rawConfig] = Object.entries(servers ?? {})[0] ?? [];
  const config = rawConfig && typeof rawConfig === "object" ? (rawConfig as Record<string, unknown>) : {};
  const url = stringValue(config.url);
  const command = stringValue(config.command);
  const args = Array.isArray(config.args) ? config.args.map(String) : [];
  const packageIdentifier = args.find((argument) => !argument.startsWith("-")) ?? "";

  return {
    source: "mcp.json",
    title: serverTitle || "",
    version: "1.0.0",
    websiteUrl: repositoryWebUrl(repositoryReference),
    repository: {
      source: GITHUB_REPOSITORY_SOURCE,
      url: repositoryReference,
    },
    remotes: url ? [{ type: "streamable-http", url }] : [],
    packages:
      command && packageIdentifier
        ? [
            {
              registryType: command.includes("uv") ? "uvx" : "npm",
              identifier: packageIdentifier,
              transport: { type: "stdio" },
            },
          ]
        : [],
  };
}

async function importSourceMetadata(
  repositoryReference: string,
  subfolder: string,
): Promise<SourceMetadata> {
  const candidates = githubRawCandidates(repositoryReference, subfolder);
  if (candidates.length === 0) {
    throw new Error("Source import currently supports GitHub repositories.");
  }
  const [githubMetadata, githubReadme] = await Promise.all([
    fetchGitHubRepositoryMetadata(repositoryReference),
    fetchGitHubReadmeDocumentation(repositoryReference, subfolder),
  ]);
  const githubFallback = { ...githubMetadata, ...githubReadme };

  for (const candidate of candidates) {
    const response = await fetch(candidate, { cache: "no-store" });
    if (!response.ok) {
      continue;
    }

    const payload = (await response.json()) as Record<string, unknown>;
    if (payload.$schema || payload.packages || payload.remotes) {
      return metadataWithFallback({
        ...(payload as SourceMetadata),
        source: "server.json",
        repository: {
          source: GITHUB_REPOSITORY_SOURCE,
          url: repositoryReference,
          subfolder,
        },
      }, githubFallback);
    }
    if (payload.mcpServers) {
      return metadataWithFallback(
        metadataFromMcpJson(payload, repositoryReference),
        githubFallback,
      );
    }
  }

  throw new Error("No server.json or mcp.json file was found in the repository root.");
}

export default function SubmitServerPage() {
  const router = useRouter();
  const [user, setUser] = useState<UserRead | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [name, setName] = useState("");
  const [isNameOverrideEnabled, setIsNameOverrideEnabled] = useState(false);
  const [title, setTitle] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [description, setDescription] = useState("");
  const [documentation, setDocumentation] = useState("");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [category, setCategory] = useState("");
  const [categories, setCategories] = useState<RegistryCategoryRead[]>([]);
  const [sourceMode, setSourceMode] = useState<SourceMode>("repository");
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [repositorySubfolder, setRepositorySubfolder] = useState("");
  const [iconUrl, setIconUrl] = useState("");
  const [remotes, setRemotes] = useState<RemoteTarget[]>([]);
  const [packages, setPackages] = useState<PackageTarget[]>([]);
  const [error, setError] = useState("");
  const [sourceImportMessage, setSourceImportMessage] = useState("");
  const [isImportingSource, setIsImportingSource] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const derivedName = generatedServerName(
    sourceMode === "repository" ? repositoryUrl : "",
    packages,
  );
  const isManualSource = sourceMode === "manual";
  const effectiveName = isManualSource || isNameOverrideEnabled ? name : name || derivedName;
  const iconPreviewUrl = iconUrl.trim();

  useEffect(() => {
    currentUser()
      .then((response) => setUser(response))
      .catch(() => setUser(null))
      .finally(() => setAuthChecked(true));
  }, []);

  useEffect(() => {
    listCategories()
      .then((response) => {
        setCategories(response.categories);
        setCategory((current) => current || response.categories[0]?.slug || "");
      })
      .catch(() => {
        setCategories([]);
        setCategory("");
      });
  }, []);

  function clearRepositoryDerivedState() {
    setSourceImportMessage("");
    if (!isNameOverrideEnabled) {
      setName("");
    }
  }

  function updateRepositoryReference(value: string) {
    setRepositoryUrl(value);
    clearRepositoryDerivedState();
  }

  function normalizeCurrentRepositoryReference() {
    setRepositoryUrl((current) => normalizeRepositoryReference(current));
  }

  function pasteRepositoryReference(event: ClipboardEvent<HTMLInputElement>) {
    const pastedValue = event.clipboardData.getData("text");
    const normalizedValue = normalizeRepositoryReference(pastedValue);
    if (normalizedValue && normalizedValue !== pastedValue.trim()) {
      event.preventDefault();
      updateRepositoryReference(normalizedValue);
    }
  }

  function updateRemote(id: string, patch: Partial<RemoteTarget>) {
    setRemotes((current) =>
      current.map((remote) => (remote.id === id ? { ...remote, ...patch } : remote)),
    );
  }

  function updateRemoteHeader(remoteId: string, headerId: string, patch: Partial<HeaderField>) {
    setRemotes((current) =>
      current.map((remote) =>
        remote.id === remoteId
          ? {
              ...remote,
              headers: remote.headers.map((header) =>
                header.id === headerId ? { ...header, ...patch } : header,
              ),
            }
          : remote,
      ),
    );
  }

  function updatePackage(id: string, patch: Partial<PackageTarget>) {
    setPackages((current) =>
      current.map((packageTarget) =>
        packageTarget.id === id ? { ...packageTarget, ...patch } : packageTarget,
      ),
    );
  }

  function updatePackageEnvironment(
    packageId: string,
    environmentId: string,
    patch: Partial<EnvironmentField>,
  ) {
    setPackages((current) =>
      current.map((packageTarget) =>
        packageTarget.id === packageId
          ? {
              ...packageTarget,
              environmentVariables: packageTarget.environmentVariables.map((envVar) =>
                envVar.id === environmentId ? { ...envVar, ...patch } : envVar,
              ),
            }
          : packageTarget,
      ),
    );
  }

  function updatePackageArgument(
    packageId: string,
    argumentId: string,
    patch: Partial<PackageArgumentField>,
  ) {
    setPackages((current) =>
      current.map((packageTarget) =>
        packageTarget.id === packageId
          ? {
              ...packageTarget,
              packageArguments: packageTarget.packageArguments.map((argument) =>
                argument.id === argumentId ? { ...argument, ...patch } : argument,
              ),
            }
          : packageTarget,
      ),
    );
  }

  async function handleImportSource() {
    setError("");
    setSourceImportMessage("");
    setIsImportingSource(true);

    try {
      const repositoryReference = normalizeRepositoryReference(repositoryUrl);
      setRepositoryUrl(repositoryReference);
      const metadata = await importSourceMetadata(
        repositoryReference,
        repositorySubfolder,
      );
      const metadataRepository = metadata.repository ?? {};
      const metadataRepositoryReference = normalizeRepositoryReference(
        metadataRepository.url || repositoryReference,
      );
      const metadataPackages = importedPackages(metadata.packages);
      const metadataRemotes = importedRemotes(metadata.remotes);
      const metadataIconUrl = metadata.iconUrl || firstIconUrl(metadata.icons);

      setSourceMode("repository");
      setRepositoryUrl(metadataRepositoryReference);
      setRepositorySubfolder(metadataRepository.subfolder || repositorySubfolder);
      setName(metadata.name || "");
      setTitle(metadata.title || "");
      setVersion("1.0.0");
      setDescription(metadata.description || "");
      setDocumentation(metadata.documentation || "");
      setWebsiteUrl(
        metadata.websiteUrl ||
          repositoryWebUrl(metadataRepositoryReference),
      );
      setIconUrl(metadataIconUrl);
      setPackages(metadataPackages);
      setRemotes(metadataRemotes);
      setSourceImportMessage(
        metadata.source === "server.json"
          ? "Registry document loaded."
          : "MCP client configuration loaded.",
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Source metadata could not be loaded.");
    } finally {
      setIsImportingSource(false);
    }
  }

  async function submitForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);

    try {
      const serverName = effectiveName.trim();
      if (!serverName) {
        throw new Error(
          isManualSource
            ? "Add a server name."
            : "Add a package target, add repository details, or override the server name.",
        );
      }
      if (!SERVER_NAME_PATTERN.test(serverName)) {
        throw new Error("Server name must use the publisher/server format.");
      }
      if (!SERVER_VERSION_PATTERN.test(version.trim())) {
        throw new Error("Server version must be a semantic version, starting at 1.0.0 for new submissions.");
      }

      const remotePayload = remotes
        .filter((remote) => remote.url.trim())
        .map((remote) => ({
          type: remote.type.trim() || "streamable-http",
          url: remote.url.trim(),
          headers: publicHeaders(remote.headers),
        }));
      const packagePayload = packages
        .filter((packageTarget) => packageTarget.identifier.trim())
        .map((packageTarget) => {
          const packageVersion = packageTarget.version.trim();
          return {
            registryType: packageTarget.registryType.trim() || "npm",
            identifier: packageTarget.identifier.trim(),
            ...(packageVersion ? { version: packageVersion } : {}),
            transport: { type: packageTarget.transportType.trim() || "stdio" },
            environmentVariables: publicEnvironment(packageTarget.environmentVariables),
            packageArguments: publicPackageArguments(packageTarget.packageArguments),
          };
        });

      if (remotePayload.length === 0 && packagePayload.length === 0) {
        throw new Error("Add at least one remote endpoint or package target.");
      }

      const repositoryReference = normalizeRepositoryReference(repositoryUrl);
      const repository = sourceMode === "repository" && repositoryReference
        ? {
            source: GITHUB_REPOSITORY_SOURCE,
            url: repositoryReference,
            subfolder: repositorySubfolder.trim(),
          }
        : null;
      const icons = iconUrl.trim()
        ? [
            {
              src: iconUrl.trim(),
              sizes: ["any"],
            },
          ]
        : [];
      const serverJson = {
        $schema: DEFAULT_SCHEMA,
        name: serverName,
        title: title.trim(),
        description: description.trim(),
        documentation: documentation.trim(),
        version: version.trim(),
        websiteUrl: websiteUrl.trim(),
        repository,
        remotes: remotePayload,
        packages: packagePayload,
        icons,
        ...(category
          ? {
              _meta: {
                [PUBLISHER_META_KEY]: {
                  category,
                },
              },
            }
          : {}),
      };

      const draft = await createSubmission({
        submissionType: "new_server",
        serverJson,
      });
      await submissionAction(draft.id, "submit");
      setSourceImportMessage("");
      router.push("/submissions");
    } catch (caught) {
      if (caught instanceof HubApiError) {
        setError(caught.message);
      } else {
        setError(caught instanceof Error ? caught.message : "Submission failed.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="min-h-dvh bg-background px-5 py-6">
      <div className="mx-auto grid w-full max-w-[1100px] gap-5">
        <header className="flex min-h-10 items-center justify-between gap-4">
          <Link className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground" href="/">
            <ArrowLeft size={16} />
            Back to registry
          </Link>
          <div className="inline-flex items-center gap-2 text-sm font-semibold">
            <Database size={18} />
            Wardn Hub
          </div>
        </header>

        <section className="grid gap-1 border-b border-border pb-4">
          <p className="eyebrow">MCP Registry</p>
          <h1 className="text-balance text-2xl leading-8 font-semibold">Submit server</h1>
          <p className="max-w-[680px] text-pretty text-sm text-muted-foreground">
            Provide the registry document details for review. Approved submissions become public server cards.
          </p>
        </section>

        {!authChecked && (
          <Card>
            <CardContent>
              <p className="text-sm text-muted-foreground">Checking session.</p>
            </CardContent>
          </Card>
        )}

        {authChecked && !user && (
          <Card>
            <CardHeader>
              <CardTitle>Sign in required</CardTitle>
              <CardDescription>Use your account before submitting a registry entry.</CardDescription>
            </CardHeader>
            <CardContent>
              <Button asChild>
                <Link href="/login?next=submit">Sign in to submit</Link>
              </Button>
            </CardContent>
          </Card>
        )}

        {authChecked && user && (
          <form className="space-y-5" onSubmit={submitForm}>
            {error ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            ) : null}

            <Card>
              <CardHeader className="flex items-center justify-between gap-3 space-y-0">
                <div>
                  <CardTitle>Submission source</CardTitle>
                  <CardDescription>Import from a public repository or switch to manual entry.</CardDescription>
                </div>
                {sourceMode === "repository" ? (
                  <Button
                    disabled={!repositoryUrl.trim() || isImportingSource}
                    onClick={handleImportSource}
                    type="button"
                    variant="outline"
                  >
                    {isImportingSource ? "Importing" : "Import"}
                  </Button>
                ) : null}
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  <button
                    aria-pressed={sourceMode === "manual"}
                    className={
                      sourceMode === "manual"
                        ? "inline-flex h-9 items-center justify-center rounded-[var(--radius)] bg-slate-900 px-4 text-sm font-medium text-white shadow-[var(--shadow-card)] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30"
                        : "inline-flex h-9 items-center justify-center rounded-[var(--radius)] border border-border bg-card px-4 text-sm font-medium text-foreground shadow-[var(--shadow-card)] outline-none hover:bg-muted focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30"
                    }
                    onClick={() => {
                      setSourceMode("manual");
                      setSourceImportMessage("");
                    }}
                    type="button"
                  >
                    Manual entry
                  </button>
                  <button
                    aria-pressed={sourceMode === "repository"}
                    className={
                      sourceMode === "repository"
                        ? "inline-flex h-9 items-center justify-center rounded-[var(--radius)] bg-slate-900 px-4 text-sm font-medium text-white shadow-[var(--shadow-card)] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30"
                        : "inline-flex h-9 items-center justify-center rounded-[var(--radius)] border border-border bg-card px-4 text-sm font-medium text-foreground shadow-[var(--shadow-card)] outline-none hover:bg-muted focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30"
                    }
                    onClick={() => setSourceMode("repository")}
                    type="button"
                  >
                    Public repository
                  </button>
                </div>

                {sourceMode === "repository" ? (
                  <div className="grid w-full gap-4 md:grid-cols-2">
                    <div className="grid gap-2">
                      <Label htmlFor="server-repository-url">GitHub repository</Label>
                      <Input
                        id="server-repository-url"
                        onBlur={normalizeCurrentRepositoryReference}
                        onChange={(event) => updateRepositoryReference(event.target.value)}
                        onPaste={pasteRepositoryReference}
                        placeholder="owner/repo"
                        value={repositoryUrl}
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="server-repository-subfolder">Repository Subfolder</Label>
                      <Input
                        id="server-repository-subfolder"
                        onChange={(event) => setRepositorySubfolder(event.target.value)}
                        value={repositorySubfolder}
                      />
                    </div>
                  </div>
                ) : null}

                {sourceImportMessage ? (
                  <div className="rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
                    {sourceImportMessage}
                  </div>
                ) : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Server</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-2">
                <div className="grid gap-2">
                  <div className="flex items-center justify-between gap-3">
                    <Label htmlFor="server-name">Name</Label>
                    {!isManualSource ? (
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          checked={isNameOverrideEnabled}
                          onChange={(event) => {
                            const isEnabled = event.target.checked;
                            setIsNameOverrideEnabled(isEnabled);
                            if (isEnabled && !name.trim()) {
                              setName(derivedName);
                            }
                          }}
                          type="checkbox"
                        />
                        Override
                      </label>
                    ) : null}
                  </div>
                  <Input
                    id="server-name"
                    onChange={(event) => setName(event.target.value)}
                    placeholder={isManualSource || isNameOverrideEnabled ? "publisher/server" : "Generated from source"}
                    readOnly={!isManualSource && !isNameOverrideEnabled}
                    required={isManualSource || isNameOverrideEnabled}
                    value={effectiveName}
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="server-version">Version</Label>
                  <Input
                    id="server-version"
                    onChange={(event) => setVersion(event.target.value)}
                    pattern={SERVER_VERSION_PATTERN.source}
                    placeholder="1.0.0"
                    required
                    value={version}
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="server-title">Title</Label>
                  <Input
                    id="server-title"
                    onChange={(event) => setTitle(event.target.value)}
                    placeholder="Grafana"
                    value={title}
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="server-category">Category</Label>
                  <Select onValueChange={(value) => setCategory(value)} value={category}>
                    <SelectTrigger id="server-category">
                      <SelectValue placeholder="Select category" />
                    </SelectTrigger>
                    <SelectContent>
                      {categories.map((item) => (
                        <SelectItem key={item.slug} value={item.slug}>
                          {item.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="server-website">Website URL</Label>
                  <Input
                    id="server-website"
                    onChange={(event) => setWebsiteUrl(event.target.value)}
                    placeholder="https://example.com"
                    type="url"
                    value={websiteUrl}
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="server-icon-url">Icon URL</Label>
                  <div className="grid grid-cols-[minmax(0,1fr)_2.5rem] items-center gap-3">
                    <Input
                      id="server-icon-url"
                      onChange={(event) => setIconUrl(event.target.value)}
                      placeholder="https://example.com/icon.svg"
                      value={iconUrl}
                    />
                    <div
                      aria-hidden={!iconPreviewUrl}
                      aria-label={iconPreviewUrl ? "Icon preview" : undefined}
                      className="size-10 rounded-md border border-border bg-card bg-contain bg-center bg-no-repeat"
                      role={iconPreviewUrl ? "img" : undefined}
                      style={
                        iconPreviewUrl
                          ? { backgroundImage: `url(${JSON.stringify(iconPreviewUrl)})` }
                          : undefined
                      }
                    />
                  </div>
                </div>
                <div className="grid gap-2 md:col-span-2">
                  <Label htmlFor="server-description">Description</Label>
                  <Input
                    id="server-description"
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="Short server description"
                    required
                    value={description}
                  />
                </div>
                <div className="grid gap-2 md:col-span-2">
                  <Label htmlFor="server-documentation">Documentation</Label>
                  <textarea
                    className="min-h-56 rounded-[var(--radius)] border border-input bg-card px-3 py-2 text-sm shadow-[var(--shadow-card)] outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25"
                    id="server-documentation"
                    onChange={(event) => setDocumentation(event.target.value)}
                    placeholder="README or usage documentation"
                    value={documentation}
                  />
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex items-center justify-between gap-3 space-y-0">
                <CardTitle>Remote Endpoints</CardTitle>
                <Button onClick={() => setRemotes((current) => [...current, emptyRemote()])} type="button" variant="outline">
                  <Plus className="size-4" />
                  Add remote
                </Button>
              </CardHeader>
              <CardContent className="space-y-4">
                {remotes.length === 0 ? (
                  <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                    No remote endpoints added.
                  </div>
                ) : null}
                {remotes.map((remote, index) => (
                  <div className="space-y-4 rounded-md border p-4" key={remote.id}>
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium">Remote {index + 1}</div>
                      <Button
                        aria-label={`Remove remote ${index + 1}`}
                        onClick={() => setRemotes((current) => current.filter((item) => item.id !== remote.id))}
                        size="icon"
                        type="button"
                        variant="outline"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                    <div className="grid gap-4 md:grid-cols-[180px_minmax(0,1fr)]">
                      <div className="grid gap-2">
                        <Label htmlFor={`${remote.id}-type`}>Transport</Label>
                        <Select
                          onValueChange={(value) => updateRemote(remote.id, { type: value })}
                          value={remote.type}
                        >
                          <SelectTrigger id={`${remote.id}-type`}>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {TRANSPORT_OPTIONS.filter((option) => option.value !== "stdio").map((option) => (
                              <SelectItem key={option.value} value={option.value}>
                                {option.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="grid gap-2">
                        <Label htmlFor={`${remote.id}-url`}>URL</Label>
                        <Input
                          id={`${remote.id}-url`}
                          onChange={(event) => updateRemote(remote.id, { url: event.target.value })}
                          placeholder="https://example.com/mcp"
                          type="url"
                          value={remote.url}
                        />
                      </div>
                    </div>
                    <div className="space-y-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-medium">Headers</div>
                        <Button
                          onClick={() =>
                            updateRemote(remote.id, { headers: [...remote.headers, emptyHeader()] })
                          }
                          size="sm"
                          type="button"
                          variant="outline"
                        >
                          <Plus className="size-4" />
                          Add header
                        </Button>
                      </div>
                      {remote.headers.map((header) => (
                        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_auto_auto_auto]" key={header.id}>
                          <Input
                            onChange={(event) =>
                              updateRemoteHeader(remote.id, header.id, { name: event.target.value })
                            }
                            placeholder="Header name"
                            value={header.name}
                          />
                          <Input
                            onChange={(event) =>
                              updateRemoteHeader(remote.id, header.id, { description: event.target.value })
                            }
                            placeholder="Description"
                            value={header.description}
                          />
                          <label className="flex items-center gap-2 text-sm">
                            <input
                              checked={header.required}
                              onChange={(event) =>
                                updateRemoteHeader(remote.id, header.id, { required: event.target.checked })
                              }
                              type="checkbox"
                            />
                            Required
                          </label>
                          <label className="flex items-center gap-2 text-sm">
                            <input
                              checked={header.secret}
                              onChange={(event) =>
                                updateRemoteHeader(remote.id, header.id, { secret: event.target.checked })
                              }
                              type="checkbox"
                            />
                            Secret
                          </label>
                          <Button
                            aria-label="Remove header"
                            onClick={() =>
                              updateRemote(remote.id, {
                                headers: remote.headers.filter((item) => item.id !== header.id),
                              })
                            }
                            size="icon"
                            type="button"
                            variant="outline"
                          >
                            <Trash2 className="size-4" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex items-center justify-between gap-3 space-y-0">
                <CardTitle>Package Targets</CardTitle>
                <Button onClick={() => setPackages((current) => [...current, emptyPackage()])} type="button" variant="outline">
                  <Plus className="size-4" />
                  Add package
                </Button>
              </CardHeader>
              <CardContent className="space-y-4">
                {packages.map((packageTarget, index) => (
                  <div className="space-y-4 rounded-md border p-4" key={packageTarget.id}>
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium">Package {index + 1}</div>
                      <Button
                        aria-label={`Remove package ${index + 1}`}
                        onClick={() =>
                          setPackages((current) => current.filter((item) => item.id !== packageTarget.id))
                        }
                        size="icon"
                        type="button"
                        variant="outline"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                    <div className="grid gap-4 md:grid-cols-[180px_minmax(0,1fr)_160px_180px]">
                      <div className="grid gap-2">
                        <Label htmlFor={`${packageTarget.id}-registry`}>Runtime</Label>
                        <Select
                          onValueChange={(value) => updatePackage(packageTarget.id, { registryType: value })}
                          value={packageTarget.registryType}
                        >
                          <SelectTrigger id={`${packageTarget.id}-registry`}>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {PACKAGE_RUNTIME_OPTIONS.map((option) => (
                              <SelectItem key={option.value} value={option.value}>
                                {option.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="grid gap-2">
                        <Label htmlFor={`${packageTarget.id}-identifier`}>Package</Label>
                        <Input
                          id={`${packageTarget.id}-identifier`}
                          onChange={(event) =>
                            updatePackage(packageTarget.id, { identifier: event.target.value })
                          }
                          placeholder="@scope/package"
                          value={packageTarget.identifier}
                        />
                      </div>
                      <div className="grid gap-2">
                        <Label htmlFor={`${packageTarget.id}-version`}>Version</Label>
                        <Input
                          id={`${packageTarget.id}-version`}
                          onChange={(event) =>
                            updatePackage(packageTarget.id, { version: event.target.value })
                          }
                          placeholder="optional package version"
                          value={packageTarget.version}
                        />
                      </div>
                      <div className="grid gap-2">
                        <Label htmlFor={`${packageTarget.id}-transport`}>Transport</Label>
                        <Select
                          onValueChange={(value) => updatePackage(packageTarget.id, { transportType: value })}
                          value={packageTarget.transportType}
                        >
                          <SelectTrigger id={`${packageTarget.id}-transport`}>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {TRANSPORT_OPTIONS.map((option) => (
                              <SelectItem key={option.value} value={option.value}>
                                {option.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    <div className="space-y-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-medium">Environment Variables</div>
                        <Button
                          onClick={() =>
                            updatePackage(packageTarget.id, {
                              environmentVariables: [
                                ...packageTarget.environmentVariables,
                                emptyEnvironment(),
                              ],
                            })
                          }
                          size="sm"
                          type="button"
                          variant="outline"
                        >
                          <Plus className="size-4" />
                          Add variable
                        </Button>
                      </div>
                      {packageTarget.environmentVariables.map((envVar) => (
                        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_minmax(0,1fr)_140px_auto_auto_auto]" key={envVar.id}>
                          <Input
                            onChange={(event) =>
                              updatePackageEnvironment(packageTarget.id, envVar.id, {
                                name: event.target.value,
                              })
                            }
                            placeholder="Variable name"
                            value={envVar.name}
                          />
                          <Input
                            onChange={(event) =>
                              updatePackageEnvironment(packageTarget.id, envVar.id, {
                                description: event.target.value,
                              })
                            }
                            placeholder="Description"
                            value={envVar.description}
                          />
                          <Input
                            onChange={(event) =>
                              updatePackageEnvironment(packageTarget.id, envVar.id, {
                                defaultValue: event.target.value,
                              })
                            }
                            placeholder="Default"
                            value={envVar.defaultValue}
                          />
                          <Select
                            onValueChange={(value) =>
                              updatePackageEnvironment(packageTarget.id, envVar.id, { format: value })
                            }
                            value={envVar.format}
                          >
                            <SelectTrigger>
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {PACKAGE_ARGUMENT_FORMAT_OPTIONS.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                  {option.label}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <label className="flex items-center gap-2 text-sm">
                            <input
                              checked={envVar.required}
                              onChange={(event) =>
                                updatePackageEnvironment(packageTarget.id, envVar.id, {
                                  required: event.target.checked,
                                })
                              }
                              type="checkbox"
                            />
                            Required
                          </label>
                          <label className="flex items-center gap-2 text-sm">
                            <input
                              checked={envVar.secret}
                              onChange={(event) =>
                                updatePackageEnvironment(packageTarget.id, envVar.id, {
                                  secret: event.target.checked,
                                })
                              }
                              type="checkbox"
                            />
                            Secret
                          </label>
                          <Button
                            aria-label="Remove environment variable"
                            onClick={() =>
                              updatePackage(packageTarget.id, {
                                environmentVariables: packageTarget.environmentVariables.filter(
                                  (item) => item.id !== envVar.id,
                                ),
                              })
                            }
                            size="icon"
                            type="button"
                            variant="outline"
                          >
                            <Trash2 className="size-4" />
                          </Button>
                        </div>
                      ))}
                    </div>
                    <div className="space-y-3 border-t pt-4">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="text-sm font-medium">Runtime Arguments</div>
                          <div className="text-xs text-muted-foreground">
                            Define static process arguments or user-configurable flags shown during installation.
                          </div>
                        </div>
                        <Button
                          onClick={() =>
                            updatePackage(packageTarget.id, {
                              packageArguments: [
                                ...packageTarget.packageArguments,
                                emptyPackageArgument(),
                              ],
                            })
                          }
                          size="sm"
                          type="button"
                          variant="outline"
                        >
                          <Plus className="size-4" />
                          Add argument
                        </Button>
                      </div>
                      {packageTarget.packageArguments.map((argument) => (
                        <div className="space-y-3 rounded-md border p-3" key={argument.id}>
                          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_140px_auto]">
                            <Input
                              onChange={(event) =>
                                updatePackageArgument(packageTarget.id, argument.id, {
                                  name: event.target.value,
                                })
                              }
                              placeholder="Config key, e.g. SERVER_LOG_LEVEL"
                              value={argument.name}
                            />
                            <Input
                              onChange={(event) =>
                                updatePackageArgument(packageTarget.id, argument.id, {
                                  flag: event.target.value,
                                })
                              }
                              placeholder="Flag, e.g. --log-level"
                              value={argument.flag}
                            />
                            <Input
                              onChange={(event) =>
                                updatePackageArgument(packageTarget.id, argument.id, {
                                  value: event.target.value,
                                })
                              }
                              placeholder="Static value, e.g. stdio"
                              value={argument.value}
                            />
                            <Select
                              onValueChange={(value) =>
                                updatePackageArgument(packageTarget.id, argument.id, { format: value })
                              }
                              value={argument.format}
                            >
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {PACKAGE_ARGUMENT_FORMAT_OPTIONS.map((option) => (
                                  <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                            <Button
                              aria-label="Remove runtime argument"
                              onClick={() =>
                                updatePackage(packageTarget.id, {
                                  packageArguments: packageTarget.packageArguments.filter(
                                    (item) => item.id !== argument.id,
                                  ),
                                })
                              }
                              size="icon"
                              type="button"
                              variant="outline"
                            >
                              <Trash2 className="size-4" />
                            </Button>
                          </div>
                          <div className="grid gap-3 md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_auto_auto]">
                            <Input
                              onChange={(event) =>
                                updatePackageArgument(packageTarget.id, argument.id, {
                                  description: event.target.value,
                                })
                              }
                              placeholder="Description"
                              value={argument.description}
                            />
                            <Input
                              onChange={(event) =>
                                updatePackageArgument(packageTarget.id, argument.id, {
                                  defaultValue: event.target.value,
                                })
                              }
                              placeholder="Default"
                              value={argument.defaultValue}
                            />
                            <Input
                              onChange={(event) =>
                                updatePackageArgument(packageTarget.id, argument.id, {
                                  options: event.target.value,
                                })
                              }
                              placeholder="Options, comma-separated"
                              value={argument.options}
                            />
                            <label className="flex items-center gap-2 text-sm">
                              <input
                                checked={argument.required}
                                onChange={(event) =>
                                  updatePackageArgument(packageTarget.id, argument.id, {
                                    required: event.target.checked,
                                  })
                                }
                                type="checkbox"
                              />
                              Required
                            </label>
                            <label className="flex items-center gap-2 text-sm">
                              <input
                                checked={argument.secret}
                                onChange={(event) =>
                                  updatePackageArgument(packageTarget.id, argument.id, {
                                    secret: event.target.checked,
                                  })
                                }
                                type="checkbox"
                              />
                              Secret
                            </label>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            <div className="flex justify-end gap-2">
              <Button asChild type="button" variant="outline">
                <Link href="/">Cancel</Link>
              </Button>
              <Button disabled={isSubmitting} type="submit">
                <Save className="size-4" />
                {isSubmitting ? "Submitting" : "Submit for review"}
              </Button>
            </div>
          </form>
        )}
      </div>
    </main>
  );
}
