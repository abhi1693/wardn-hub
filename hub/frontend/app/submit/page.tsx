"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import type { ClipboardEvent, FormEvent } from "react";
import { Suspense, useEffect, useState } from "react";
import { Plus, Save, Trash2 } from "lucide-react";

import { AiDraftFixPromptDialog } from "@/components/ai-draft-fix-prompt-dialog";
import { PageLoader } from "@/components/page-loader";
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
  submissionAction,
  updateServerVersion,
  updateSubmission,
} from "@/lib/api/hub";
import type { UserRead } from "@/lib/api/generated/model";

import {
  DEFAULT_SCHEMA,
  GITHUB_REPOSITORY_SOURCE,
  PACKAGE_ARGUMENT_FORMAT_OPTIONS,
  PACKAGE_RUNTIME_OPTIONS,
  SERVER_NAME_PATTERN,
  SERVER_VERSION_PATTERN,
  TRANSPORT_OPTIONS,
  duplicateEnvironmentNames,
  emptyEnvironment,
  emptyHeader,
  emptyPackage,
  emptyPackageArgument,
  emptyRemote,
  generatedServerName,
  hasEnvironmentPlaceholder,
  humanSourceReviewPayload,
  launchArgumentValues,
  normalizeArgumentStaticValue,
  normalizeRepositoryReference,
  parseRepositorySource,
  publicEnvironment,
  publicHeaders,
  publicPackageArguments,
  publicQueryParameters,
  serverMetaPayload,
  splitArgumentFlagRequiresValue,
  splitPackageIdentifierVersion,
  type EnvironmentField,
  type HeaderField,
  type PackageArgumentField,
  type PackageTarget,
  type RemoteTarget,
} from "./submission-draft";
import { useSubmissionDraft } from "./use-submission-draft";

function safeReturnTo(value: string | null) {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return "";
  }
  return value;
}

function SubmitServerPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const returnTo = safeReturnTo(searchParams.get("returnTo"));
  const submissionReturnPath = returnTo || "/submissions";
  const defaultReturnPath = returnTo || "/";
  const [user, setUser] = useState<UserRead | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [error, setError] = useState("");
  const [draftFixPromptOpen, setDraftFixPromptOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const {
    submissionMode,
    setSubmissionMode,
    editingSubmissionId,
    setEditingSubmissionId,
    editingSubmissionType,
    setEditingSubmissionType,
    isLoadingSubmission,
    lockedServerName,
    lockedVersion,
    name,
    setName,
    isNameOverrideEnabled,
    setIsNameOverrideEnabled,
    title,
    setTitle,
    version,
    setVersion,
    description,
    setDescription,
    documentation,
    setDocumentation,
    websiteUrl,
    setWebsiteUrl,
    category,
    setCategory,
    serverMeta,
    categories,
    partnerOwnerOrganizations,
    ownerOrganizationId,
    setOwnerOrganizationId,
    sourceMode,
    setSourceMode,
    repositoryUrl,
    setRepositoryUrl,
    repositorySubfolder,
    setRepositorySubfolder,
    iconUrl,
    setIconUrl,
    remotes,
    setRemotes,
    packages,
    setPackages,
    sourceImportMessage,
    setSourceImportMessage,
    isImportingSource,
    handleImportSource,
  } = useSubmissionDraft({ user, setError });
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
      const humanSourceReview = humanSourceReviewPayload({
        sourceMode,
        repositoryUrl,
        repositorySubfolder,
        websiteUrl,
        documentation,
        packages,
        sourceImportMessage,
      });
      const meta = serverMetaPayload(serverMeta, category, humanSourceReview);
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
        router.push(defaultReturnPath);
        return;
      }

      if (isAddingPublishedServerVersion) {
        if (canManagePublishedServers) {
          await createServerVersion(serverJson);
          setSourceImportMessage("");
          router.push(defaultReturnPath);
          return;
        }
        const draft = await createSubmission({
          ownerOrganizationId: ownerOrganizationId || null,
          submissionType: "new_version",
          serverJson,
        });
        await submissionAction(draft.id, "submit");
        setSourceImportMessage("");
        router.push(submissionReturnPath);
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
      router.push(submissionReturnPath);
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
              <PageLoader className="rounded-md border border-dashed" compact label="Loading submission" />
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
                  <Link href={defaultReturnPath}>Cancel</Link>
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

export default function SubmitServerPage() {
  return (
    <Suspense fallback={null}>
      <SubmitServerPageContent />
    </Suspense>
  );
}
