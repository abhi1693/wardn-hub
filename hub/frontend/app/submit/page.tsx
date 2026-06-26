"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ClipboardEvent, FormEvent } from "react";
import { useEffect, useState } from "react";
import { Plus, Save, Trash2 } from "lucide-react";

import { AiDraftFixPromptDialog } from "@/components/ai-draft-fix-prompt-dialog";
import { PublicHeader } from "@/components/site-header";
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
  createServerVersion,
  createSubmission,
  currentUser,
  getServer,
  getSubmission,
  importServerSource,
  listCategories,
  listOrganizations,
  listPartnerOrganizations,
  submissionAction,
  updateServerVersion,
  updateSubmission,
} from "@/lib/api/hub";
import type {
  OrganizationRead,
  RegistryCategoryRead,
  RegistryServerDetailResponse,
  RegistryServerVersionRead,
  SubmissionRead,
  UserRead,
} from "@/lib/api/generated/model";

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
  includeInLaunch: boolean;
  options: string;
  value: string;
  requiresValue: boolean;
};

type RemoteTarget = {
  id: string;
  type: string;
  url: string;
  headers: HeaderField[];
  queryParameters: HeaderField[];
};

type PackageTarget = {
  id: string;
  registryType: string;
  identifier: string;
  version: string;
  command: string;
  transportType: string;
  environmentVariables: EnvironmentField[];
  packageArguments: PackageArgumentField[];
};

type SourceMode = "manual" | "repository";
type SubmissionMode = "new" | "edit" | "new_version" | "server_edit" | "server_new_version";

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

function hasEnvironmentPlaceholder(value: string) {
  return value.includes("${") && value.includes("}");
}

function splitPackageIdentifierVersion(value: string) {
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

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    : [];
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
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
    includeInLaunch: false,
    options: "",
    value: "",
    requiresValue: false,
  };
}

function emptyRemote(): RemoteTarget {
  return {
    id: createId("remote"),
    type: "streamable-http",
    url: "",
    headers: [],
    queryParameters: [],
  };
}

function emptyPackage(): PackageTarget {
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
  return parseRepositorySource(value).repositoryUrl || value.trim();
}

function repositorySourceSubfolder(value: string) {
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

function parseRepositorySource(value: string) {
  const repository = parseRepositoryReference(value);
  if (!repository) {
    return { repositoryUrl: value.trim(), subfolder: "" };
  }

  return {
    repositoryUrl: `${repository.owner}/${repository.repo}`,
    subfolder: repositorySourceSubfolder(value),
  };
}

function repositoryWebUrl(value: string) {
  const repository = parseRepositoryReference(value);
  if (!repository) {
    return "";
  }

  return `https://${GITHUB_HOST}/${repository.owner}/${repository.repo}`;
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
    required: booleanValue(header.isRequired ?? header.required),
    secret: booleanValue(header.isSecret ?? header.secret),
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

function initialTransportEnvironment(value: unknown): EnvironmentField[] {
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

function mergeEnvironmentFields(environmentVariables: EnvironmentField[]) {
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

function duplicateEnvironmentNames(environmentVariables: EnvironmentField[]) {
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

function splitArgumentFlagRequiresValue(flag: string, fallbackRequiresValue = false) {
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

function normalizeArgumentStaticValue(value: string) {
  const trimmed = value.trim();
  if (/^(?:<[^<>]+>|\[[^\[\]]+\])$/.test(trimmed)) {
    return { value: "", requiresValue: true };
  }
  return { value, requiresValue: false };
}

function initialPackageArguments(value: unknown): PackageArgumentField[] {
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

function initialTransportArguments(value: unknown): PackageArgumentField[] {
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

function importedRemotes(value: unknown): RemoteTarget[] {
  return records(value).map((remote) => ({
    id: createId("remote"),
    type: stringValue(remote.type) || "streamable-http",
    url: stringValue(remote.url),
    headers: initialHeaders(remote.headers),
    queryParameters: initialHeaders(remote.queryParameters ?? remote.queryParams),
  }));
}

function importedPackages(value: unknown): PackageTarget[] {
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

function firstIconUrl(value: unknown) {
  const icon = records(value)[0];
  return stringValue(icon?.src);
}

function categoryFromServerJson(value: Record<string, unknown>) {
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

function serverMetaPayload(existingMeta: Record<string, unknown> | null, category: string) {
  const meta = existingMeta ? { ...existingMeta } : {};
  if (category) {
    const publisherMeta = recordValue(meta[PUBLISHER_META_KEY]);
    meta[PUBLISHER_META_KEY] = {
      ...(publisherMeta ?? {}),
      category,
    };
  }

  return Object.keys(meta).length > 0 ? meta : undefined;
}

function bumpPatchVersion(value: string) {
  const match = value.match(/^(\d+)\.(\d+)\.(\d+)$/);
  if (!match) {
    return value;
  }

  return `${match[1]}.${match[2]}.${Number(match[3]) + 1}`;
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

function publicQueryParameters(queryParameters: HeaderField[]) {
  return queryParameters
    .filter((parameter) => parameter.name.trim())
    .map((parameter) => ({
      name: parameter.name.trim(),
      description: parameter.description.trim(),
      isRequired: parameter.required,
      isSecret: parameter.secret,
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

function launchArgumentValues(packageArguments: PackageArgumentField[]) {
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

export default function SubmitServerPage() {
  const router = useRouter();
  const [user, setUser] = useState<UserRead | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [submissionMode, setSubmissionMode] = useState<SubmissionMode>("new");
  const [editingSubmissionId, setEditingSubmissionId] = useState("");
  const [editingSubmissionType, setEditingSubmissionType] =
    useState<SubmissionRead["submissionType"]>("new_server");
  const [isLoadingSubmission, setIsLoadingSubmission] = useState(false);
  const [lockedServerName, setLockedServerName] = useState("");
  const [lockedVersion, setLockedVersion] = useState("");
  const [name, setName] = useState("");
  const [isNameOverrideEnabled, setIsNameOverrideEnabled] = useState(false);
  const [title, setTitle] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [description, setDescription] = useState("");
  const [documentation, setDocumentation] = useState("");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [category, setCategory] = useState("");
  const [serverMeta, setServerMeta] = useState<Record<string, unknown> | null>(null);
  const [categories, setCategories] = useState<RegistryCategoryRead[]>([]);
  const [partnerOwnerOrganizations, setPartnerOwnerOrganizations] = useState<OrganizationRead[]>([]);
  const [ownerOrganizationId, setOwnerOrganizationId] = useState("");
  const [sourceMode, setSourceMode] = useState<SourceMode>("repository");
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [repositorySubfolder, setRepositorySubfolder] = useState("");
  const [iconUrl, setIconUrl] = useState("");
  const [remotes, setRemotes] = useState<RemoteTarget[]>([]);
  const [packages, setPackages] = useState<PackageTarget[]>([]);
  const [error, setError] = useState("");
  const [draftFixPromptOpen, setDraftFixPromptOpen] = useState(false);
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
  const isEditingExistingSubmission = submissionMode === "edit" && editingSubmissionId;
  const isAddingNewVersion = submissionMode === "new_version";
  const isEditingPublishedServer = submissionMode === "server_edit";
  const isAddingPublishedServerVersion = submissionMode === "server_new_version";
  const canManagePublishedServers = Boolean(user?.is_superuser);
  const isServerNameLocked = Boolean(lockedServerName);
  const isVersionLocked = Boolean(lockedVersion);
  const canChoosePartnerOwner =
    partnerOwnerOrganizations.length > 0 &&
    !isEditingPublishedServer &&
    !(isAddingPublishedServerVersion && canManagePublishedServers);
  const pageTitle = (() => {
    if (isAddingNewVersion) return "Add server version";
    if (isAddingPublishedServerVersion) {
      return canManagePublishedServers ? "Add MCP server version" : "Add server version";
    }
    if (isEditingPublishedServer) {
      return canManagePublishedServers ? "Edit MCP server" : "Add server version";
    }
    if (isEditingExistingSubmission) return "Edit submission";
    return "Submit server";
  })();
  const pageDescription = (() => {
    if (isAddingNewVersion) return "Create a new review submission for the same published server.";
    if (isAddingPublishedServerVersion || (isEditingPublishedServer && !canManagePublishedServers)) {
      return canManagePublishedServers
        ? "Publish a new version for this MCP server."
        : "Create a new review submission for the same published server.";
    }
    if (isEditingPublishedServer) return "Update the latest published registry document.";
    if (isEditingExistingSubmission) return "Update this submission and send it back to review.";
    return "Provide the registry document details for review. Approved submissions become public server cards.";
  })();
  const submitButtonLabel = (() => {
    if (isAddingNewVersion) return "Submit new version";
    if (isAddingPublishedServerVersion || (isEditingPublishedServer && !canManagePublishedServers)) {
      return canManagePublishedServers ? "Publish new version" : "Submit new version";
    }
    if (isEditingPublishedServer) return "Save MCP server";
    if (isEditingExistingSubmission) return "Submit update for review";
    return "Submit for review";
  })();

  useEffect(() => {
    currentUser()
      .then((response) => setUser(response))
      .catch(() => setUser(null))
      .finally(() => setAuthChecked(true));
  }, []);

  useEffect(() => {
    if (!user) {
      return;
    }

    let active = true;
    Promise.all([
      listOrganizations(),
      listPartnerOrganizations().catch(() => ({ organizations: [] })),
    ])
      .then(([organizationResponse, partnerResponse]) => {
        if (!active) return;
        const partnerIds = new Set(partnerResponse.organizations.map((partner) => partner.id));
        const partnerOrganizations = organizationResponse.organizations.filter((organization) =>
          partnerIds.has(organization.id),
        );
        setPartnerOwnerOrganizations(partnerOrganizations);
        setOwnerOrganizationId((current) =>
          current && partnerOrganizations.some((organization) => organization.id === current)
            ? current
            : "",
        );
      })
      .catch(() => {
        if (!active) return;
        setPartnerOwnerOrganizations([]);
        setOwnerOrganizationId("");
      });

    return () => {
      active = false;
    };
  }, [user]);

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

  function loadSubmissionIntoForm(submission: SubmissionRead, mode: SubmissionMode) {
    const serverJson = submission.serverJson ?? {};
    const repository = serverJson.repository && typeof serverJson.repository === "object"
      ? (serverJson.repository as Record<string, unknown>)
      : null;
    const repositoryReference = normalizeRepositoryReference(stringValue(repository?.url));
    const icons = records(serverJson.icons);

    setSubmissionMode(mode);
    setEditingSubmissionId(mode === "edit" ? submission.id : "");
    setEditingSubmissionType(mode === "new_version" ? "new_version" : submission.submissionType);
    setLockedServerName(mode === "new_version" ? submission.name : "");
    setLockedVersion("");
    setSourceMode(repositoryReference ? "repository" : "manual");
    setRepositoryUrl(repositoryReference);
    setRepositorySubfolder(stringValue(repository?.subfolder));
    setName(submission.name);
    setIsNameOverrideEnabled(true);
    setTitle(stringValue(serverJson.title));
    setVersion(mode === "new_version" ? bumpPatchVersion(submission.version) : submission.version);
    setDescription(stringValue(serverJson.description));
    setDocumentation(stringValue(serverJson.documentation));
    setWebsiteUrl(stringValue(serverJson.websiteUrl));
    setCategory(categoryFromServerJson(serverJson));
    setServerMeta(recordValue(serverJson._meta));
    setIconUrl(firstIconUrl(icons));
    setRemotes(importedRemotes(serverJson.remotes));
    setPackages(importedPackages(serverJson.packages));
    setOwnerOrganizationId(submission.ownerOrganizationId ?? "");
    setSourceImportMessage(
      mode === "new_version"
        ? "Published server loaded. Update the version before submitting."
        : "Submission loaded for editing.",
    );
  }

  function loadServerVersionIntoForm(
    response: RegistryServerDetailResponse,
    version: RegistryServerVersionRead,
    mode: "server_edit" | "server_new_version",
  ) {
    const serverJson = version.serverJson ?? {};
    const repository = serverJson.repository && typeof serverJson.repository === "object"
      ? (serverJson.repository as Record<string, unknown>)
      : null;
    const repositoryReference = normalizeRepositoryReference(stringValue(repository?.url));
    const icons = records(serverJson.icons);

    setSubmissionMode(mode);
    setEditingSubmissionId("");
    setEditingSubmissionType("new_server");
    setLockedServerName(response.server.name);
    setLockedVersion(mode === "server_edit" ? version.version : "");
    setSourceMode(repositoryReference ? "repository" : "manual");
    setRepositoryUrl(repositoryReference);
    setRepositorySubfolder(stringValue(repository?.subfolder));
    setName(response.server.name);
    setIsNameOverrideEnabled(true);
    setTitle(stringValue(serverJson.title) || response.server.title);
    setVersion(mode === "server_new_version" ? bumpPatchVersion(version.version) : version.version);
    setDescription(stringValue(serverJson.description) || response.server.description);
    setDocumentation(stringValue(serverJson.documentation) || response.server.documentation || "");
    setWebsiteUrl(stringValue(serverJson.websiteUrl) || response.server.websiteUrl || "");
    setCategory(categoryFromServerJson(serverJson));
    setServerMeta(recordValue(serverJson._meta));
    setIconUrl(firstIconUrl(icons));
    setRemotes(importedRemotes(serverJson.remotes));
    setPackages(importedPackages(serverJson.packages));
    setOwnerOrganizationId(response.server.organization?.id ?? "");
    setSourceImportMessage(
      mode === "server_new_version"
        ? "Published server loaded. Update the version before publishing."
        : "Published server loaded for editing.",
    );
  }

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      const searchParams = new URLSearchParams(window.location.search);
      const submissionId = searchParams.get("submission") ?? "";
      const serverName = searchParams.get("server") ?? "";
      if (!submissionId && !serverName) {
        return;
      }

      if (serverName) {
        const requestedVersion = searchParams.get("version") ?? "latest";
        const requestedMode = requestedVersion === "new" ? "server_new_version" : "server_edit";
        setIsLoadingSubmission(true);
        setError("");
        getServer(serverName)
          .then((response) => {
            const versions = response.versions ?? [];
            const version = requestedVersion === "new"
              ? versions.find((item) => item.isLatest) ?? versions[0]
              : versions.find((item) => item.version === requestedVersion)
                ?? versions.find((item) => item.isLatest)
                ?? versions[0];
            if (!version) {
              setError("Server version could not be loaded.");
              return;
            }
            loadServerVersionIntoForm(response, version, requestedMode);
          })
          .catch((caught) => {
            setError(caught instanceof Error ? caught.message : "Server could not be loaded.");
          })
          .finally(() => setIsLoadingSubmission(false));
        return;
      }

      const requestedMode: SubmissionMode = searchParams.get("version") === "new" ? "new_version" : "edit";
      setIsLoadingSubmission(true);
      setError("");
      getSubmission(submissionId)
        .then((submission) => {
          if (submission.status === "published" && requestedMode !== "new_version") {
            setError("Published submissions cannot be edited. Add a new version instead.");
            return;
          }
          loadSubmissionIntoForm(submission, requestedMode);
        })
        .catch((caught) => {
          setError(caught instanceof Error ? caught.message : "Submission could not be loaded.");
        })
        .finally(() => setIsLoadingSubmission(false));
    }, 0);
    return () => window.clearTimeout(timeoutId);
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
    const source = parseRepositorySource(repositoryUrl);
    setRepositoryUrl(source.repositoryUrl || repositoryUrl.trim());
    if (source.subfolder) {
      setRepositorySubfolder(source.subfolder);
    }
  }

  function pasteRepositoryReference(event: ClipboardEvent<HTMLInputElement>) {
    const pastedValue = event.clipboardData.getData("text");
    const source = parseRepositorySource(pastedValue);
    if (
      source.repositoryUrl &&
      (source.repositoryUrl !== pastedValue.trim() || source.subfolder)
    ) {
      event.preventDefault();
      updateRepositoryReference(source.repositoryUrl);
      if (source.subfolder) {
        setRepositorySubfolder(source.subfolder);
      }
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

  function updateRemoteQueryParameter(
    remoteId: string,
    parameterId: string,
    patch: Partial<HeaderField>,
  ) {
    setRemotes((current) =>
      current.map((remote) =>
        remote.id === remoteId
          ? {
              ...remote,
              queryParameters: remote.queryParameters.map((parameter) =>
                parameter.id === parameterId ? { ...parameter, ...patch } : parameter,
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

  function updatePackageIdentifier(id: string, value: string) {
    const parsedPackage = splitPackageIdentifierVersion(value);
    setPackages((current) =>
      current.map((packageTarget) =>
        packageTarget.id === id
          ? {
              ...packageTarget,
              identifier: parsedPackage.identifier,
              ...(parsedPackage.version ? { version: parsedPackage.version } : {}),
            }
          : packageTarget,
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
      const metadata = await importServerSource({
        repositoryUrl: repositoryReference,
        subfolder: repositorySubfolder,
      });
      const metadataRepository = metadata.repository ?? {};
      const metadataRepositoryReference = normalizeRepositoryReference(
        stringValue(metadataRepository.url) || repositoryReference,
      );
      const metadataPackages = importedPackages(metadata.packages);
      const metadataRemotes = importedRemotes(metadata.remotes);
      const metadataIconUrl = metadata.iconUrl || firstIconUrl(metadata.icons);

      setSourceMode("repository");
      setRepositoryUrl(metadataRepositoryReference);
      setRepositorySubfolder(stringValue(metadataRepository.subfolder) || repositorySubfolder);
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
      setServerMeta(null);
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
        throw new Error("Server version must be a semantic version.");
      }
      if (submissionMode === "new" && version.trim() !== "1.0.0") {
        throw new Error("New server submissions must start at version 1.0.0.");
      }
      if ((isAddingNewVersion || isAddingPublishedServerVersion) && serverName !== lockedServerName) {
        throw new Error("New versions must use the published server name.");
      }
      if (isEditingPublishedServer && version.trim() !== lockedVersion) {
        throw new Error("Published server edits must keep the same version.");
      }

      const remotePayload = remotes
        .filter((remote) => remote.url.trim())
        .map((remote) => ({
          type: remote.type.trim() || "streamable-http",
          url: remote.url.trim(),
          headers: publicHeaders(remote.headers),
          queryParameters: publicQueryParameters(remote.queryParameters),
        }));
      const packagePayload = packages
        .filter((packageTarget) => packageTarget.identifier.trim())
        .map((packageTarget) => {
          const parsedPackage = splitPackageIdentifierVersion(packageTarget.identifier);
          if (parsedPackage.version) {
            throw new Error("Move package versions into the Version field.");
          }
          const packageVersion = packageTarget.version.trim();
          const command = packageTarget.command.trim();
          const placeholderEnvVar = packageTarget.environmentVariables.find((envVar) =>
            hasEnvironmentPlaceholder(envVar.defaultValue),
          );
          if (placeholderEnvVar) {
            throw new Error(
              `Do not use ${placeholderEnvVar.defaultValue} as a value. Leave ${placeholderEnvVar.name || "the variable"} empty for user-supplied secrets.`,
            );
          }
          const duplicateEnvNames = duplicateEnvironmentNames(packageTarget.environmentVariables);
          if (duplicateEnvNames.length > 0) {
            throw new Error(
              `Remove duplicate environment variables from ${packageTarget.identifier || "the package"}: ${duplicateEnvNames.join(", ")}.`,
            );
          }
          const placeholderArgument = packageTarget.packageArguments.find((argument) =>
            hasEnvironmentPlaceholder(argument.value) || hasEnvironmentPlaceholder(argument.defaultValue),
          );
          if (placeholderArgument) {
            throw new Error("Do not use ${...} placeholders in runtime argument values.");
          }
          const transportEnv = Object.fromEntries(
            packageTarget.environmentVariables
              .filter((envVar) => envVar.name.trim())
              .map((envVar) => [envVar.name.trim(), envVar.defaultValue.trim()]),
          );
          const transportArgs = launchArgumentValues(packageTarget.packageArguments);
          return {
            registryType: packageTarget.registryType.trim() || "npm",
            identifier: packageTarget.identifier.trim(),
            ...(packageVersion ? { version: packageVersion } : {}),
            transport: {
              type: packageTarget.transportType.trim() || "stdio",
              ...(command ? { command } : {}),
              ...(transportArgs.length > 0 ? { args: transportArgs } : {}),
              ...(Object.keys(transportEnv).length > 0 ? { env: transportEnv } : {}),
            },
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
      const meta = serverMetaPayload(serverMeta, category);
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
        ...(meta ? { _meta: meta } : {}),
      };

      if (isEditingPublishedServer && !canManagePublishedServers) {
        throw new Error("Published server edits must be submitted as a new version.");
      }

      if (isEditingPublishedServer) {
        await updateServerVersion(lockedServerName, lockedVersion, serverJson);
        setSourceImportMessage("");
        router.push("/");
        return;
      }

      if (isAddingPublishedServerVersion) {
        if (canManagePublishedServers) {
          await createServerVersion(serverJson);
          setSourceImportMessage("");
          router.push("/");
          return;
        }
        const draft = await createSubmission({
          ownerOrganizationId: ownerOrganizationId || null,
          submissionType: "new_version",
          serverJson,
        });
        await submissionAction(draft.id, "submit");
        setSourceImportMessage("");
        router.push("/submissions");
        return;
      }

      const submissionType = isAddingNewVersion ? "new_version" : editingSubmissionType;
      const draft = isEditingExistingSubmission
        ? await updateSubmission(editingSubmissionId, {
            ownerOrganizationId: ownerOrganizationId || null,
            submissionType,
            serverJson,
          })
        : await createSubmission({
            ownerOrganizationId: ownerOrganizationId || null,
            submissionType,
            serverJson,
          });
      setSubmissionMode("edit");
      setEditingSubmissionId(draft.id);
      setEditingSubmissionType(draft.submissionType);
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
    <>
      <PublicHeader />
      <main className="min-h-[calc(100dvh-64px)] bg-background px-5 py-6">
      <div className="mx-auto grid w-full max-w-[var(--content-max-width)] gap-5">
        <section className="grid gap-1 border-b border-border pb-4">
          <p className="eyebrow">MCP Registry</p>
          <h1 className="text-balance text-2xl leading-8 font-semibold">{pageTitle}</h1>
          <p className="max-w-[680px] text-pretty text-sm text-muted-foreground">
            {pageDescription}
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
            {isLoadingSubmission ? (
              <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                Loading submission.
              </div>
            ) : null}

            {canChoosePartnerOwner ? (
              <Card>
                <CardHeader>
                  <CardTitle>Owner</CardTitle>
                  <CardDescription>
                    Submit this server as yourself or as a partner organization you belong to.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="grid gap-2 md:max-w-md">
                    <Label htmlFor="submission-owner-organization">Partner organization</Label>
                    <Select
                      onValueChange={(value) =>
                        setOwnerOrganizationId(value === "__personal__" ? "" : value)
                      }
                      value={ownerOrganizationId || "__personal__"}
                    >
                      <SelectTrigger id="submission-owner-organization">
                        <SelectValue placeholder="Select owner" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__personal__">Personal account</SelectItem>
                        {partnerOwnerOrganizations.map((organization) => (
                          <SelectItem key={organization.id} value={organization.id}>
                            {organization.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </CardContent>
              </Card>
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
                        placeholder="owner/repo or GitHub tree URL"
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
                    {!isManualSource && !isServerNameLocked ? (
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
                    onChange={(event) => {
                      if (!isServerNameLocked) {
                        setName(event.target.value);
                      }
                    }}
                    placeholder={
                      isManualSource || isNameOverrideEnabled || isServerNameLocked
                        ? "publisher/server"
                        : "Generated from source"
                    }
                    readOnly={isServerNameLocked || (!isManualSource && !isNameOverrideEnabled)}
                    required={isManualSource || isNameOverrideEnabled || isServerNameLocked}
                    value={effectiveName}
                  />
                  {isServerNameLocked ? (
                    <p className="text-xs text-muted-foreground">
                      New versions must use the same server name.
                    </p>
                  ) : null}
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="server-version">Version</Label>
                  <Input
                    id="server-version"
                    onChange={(event) => {
                      if (!isVersionLocked) {
                        setVersion(event.target.value);
                      }
                    }}
                    pattern={SERVER_VERSION_PATTERN.source}
                    placeholder="1.0.0"
                    readOnly={isVersionLocked}
                    required
                    value={version}
                  />
                  {isVersionLocked ? (
                    <p className="text-xs text-muted-foreground">
                      Published server edits keep the current version.
                    </p>
                  ) : null}
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
                    <div className="space-y-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-medium">Query Parameters</div>
                        <Button
                          onClick={() =>
                            updateRemote(remote.id, {
                              queryParameters: [...remote.queryParameters, emptyHeader()],
                            })
                          }
                          size="sm"
                          type="button"
                          variant="outline"
                        >
                          <Plus className="size-4" />
                          Add parameter
                        </Button>
                      </div>
                      {remote.queryParameters.map((parameter) => (
                        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_auto_auto_auto]" key={parameter.id}>
                          <Input
                            onChange={(event) =>
                              updateRemoteQueryParameter(remote.id, parameter.id, {
                                name: event.target.value,
                              })
                            }
                            placeholder="Parameter name"
                            value={parameter.name}
                          />
                          <Input
                            onChange={(event) =>
                              updateRemoteQueryParameter(remote.id, parameter.id, {
                                description: event.target.value,
                              })
                            }
                            placeholder="Description"
                            value={parameter.description}
                          />
                          <label className="flex items-center gap-2 text-sm">
                            <input
                              checked={parameter.required}
                              onChange={(event) =>
                                updateRemoteQueryParameter(remote.id, parameter.id, {
                                  required: event.target.checked,
                                })
                              }
                              type="checkbox"
                            />
                            Required
                          </label>
                          <label className="flex items-center gap-2 text-sm">
                            <input
                              checked={parameter.secret}
                              onChange={(event) =>
                                updateRemoteQueryParameter(remote.id, parameter.id, {
                                  secret: event.target.checked,
                                })
                              }
                              type="checkbox"
                            />
                            Secret
                          </label>
                          <Button
                            aria-label="Remove query parameter"
                            onClick={() =>
                              updateRemote(remote.id, {
                                queryParameters: remote.queryParameters.filter(
                                  (item) => item.id !== parameter.id,
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
                            updatePackageIdentifier(packageTarget.id, event.target.value)
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
                    <div className="grid gap-4 md:grid-cols-[180px_minmax(0,1fr)]">
                      <div className="grid gap-2">
                        <Label htmlFor={`${packageTarget.id}-command`}>Command</Label>
                        <Input
                          id={`${packageTarget.id}-command`}
                          onChange={(event) =>
                            updatePackage(packageTarget.id, { command: event.target.value })
                          }
                          placeholder="npx"
                          value={packageTarget.command}
                        />
                      </div>
                      <div className="grid gap-2">
                        <Label>Resolved launch</Label>
                        <div className="min-h-9 overflow-x-auto whitespace-nowrap rounded-md border bg-muted/30 px-3 py-2 text-sm">
                          {[packageTarget.command, ...launchArgumentValues(packageTarget.packageArguments)]
                            .filter(Boolean)
                            .join(" ") || "Not configured"}
                        </div>
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
                          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.75fr)_140px_auto]">
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
                                {
                                  const parsedFlag = splitArgumentFlagRequiresValue(
                                    event.target.value,
                                    argument.requiresValue,
                                  );
                                  updatePackageArgument(packageTarget.id, argument.id, {
                                    flag: parsedFlag.flag,
                                    requiresValue: parsedFlag.requiresValue,
                                  });
                                }
                              }
                              placeholder="Flag, e.g. --log-level"
                              value={argument.flag}
                            />
                            <Input
                              onChange={(event) =>
                                {
                                  const normalizedValue = normalizeArgumentStaticValue(
                                    event.target.value,
                                  );
                                  updatePackageArgument(packageTarget.id, argument.id, {
                                    value: normalizedValue.value,
                                    requiresValue:
                                      normalizedValue.requiresValue || argument.requiresValue,
                                  });
                                }
                              }
                              placeholder="Static value, e.g. stdio"
                              value={argument.value}
                            />
                            <label className="flex items-center gap-2 text-sm">
                              <input
                                checked={argument.requiresValue}
                                onChange={(event) =>
                                  updatePackageArgument(packageTarget.id, argument.id, {
                                    requiresValue: event.target.checked,
                                  })
                                }
                                type="checkbox"
                              />
                              Takes value
                            </label>
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
                          <div className="grid gap-3 md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_auto_auto_auto]">
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
                                checked={argument.includeInLaunch}
                                onChange={(event) =>
                                  updatePackageArgument(packageTarget.id, argument.id, {
                                    includeInLaunch: event.target.checked,
                                  })
                                }
                                type="checkbox"
                              />
                              Launch
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

            <div className="sticky bottom-0 z-10 -mx-5 border-t border-border bg-background/95 px-5 py-4 backdrop-blur">
              {error ? (
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  <span>{error}</span>
                  {editingSubmissionId ? (
                    <Button
                      onClick={() => setDraftFixPromptOpen(true)}
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      Fix with AI
                    </Button>
                  ) : null}
                </div>
              ) : null}
              <div className="flex justify-end gap-2">
                <Button asChild type="button" variant="outline">
                  <Link href="/">Cancel</Link>
                </Button>
                <Button disabled={isSubmitting} type="submit">
                  <Save className="size-4" />
                  {isSubmitting ? "Submitting" : submitButtonLabel}
                </Button>
              </div>
            </div>
          </form>
        )}
        </div>
      </main>
      <AiDraftFixPromptDialog
        errorMessage={error}
        onOpenChange={setDraftFixPromptOpen}
        open={draftFixPromptOpen}
        serverName={effectiveName}
        submissionId={editingSubmissionId}
      />
    </>
  );
}
