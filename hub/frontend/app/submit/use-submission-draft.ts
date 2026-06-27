import { useCallback, useEffect, useState } from "react";

import {
  getServer,
  getSubmission,
  importServerSource,
  listCategories,
  listOrganizations,
  listPartnerOrganizations,
} from "@/lib/api/hub";
import type {
  OrganizationRead,
  RegistryCategoryRead,
  SubmissionRead,
  UserRead,
} from "@/lib/api/generated/model";

import {
  importedPackages,
  importedRemotes,
  normalizeRepositoryReference,
  publishedServerDraftValues,
  recordValue,
  repositoryWebUrl,
  stringValue,
  submissionDraftValues,
  type PackageTarget,
  type RemoteTarget,
  type SourceMode,
  type SubmissionDraftValues,
  type SubmissionMode,
} from "./submission-draft";

type UseSubmissionDraftOptions = {
  user: UserRead | null;
  setError: (message: string) => void;
};

function firstIconUrlFromMetadata(metadata: { iconUrl?: string; icons?: unknown }) {
  const icon = Array.isArray(metadata.icons) ? metadata.icons[0] : null;
  return metadata.iconUrl || stringValue(recordValue(icon)?.src);
}

export function useSubmissionDraft({ user, setError }: UseSubmissionDraftOptions) {
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
  const [partnerOwnerOrganizations, setPartnerOwnerOrganizations] = useState<OrganizationRead[]>(
    [],
  );
  const [ownerOrganizationId, setOwnerOrganizationId] = useState("");
  const [sourceMode, setSourceMode] = useState<SourceMode>("repository");
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [repositorySubfolder, setRepositorySubfolder] = useState("");
  const [iconUrl, setIconUrl] = useState("");
  const [remotes, setRemotes] = useState<RemoteTarget[]>([]);
  const [packages, setPackages] = useState<PackageTarget[]>([]);
  const [sourceImportMessage, setSourceImportMessage] = useState("");
  const [isImportingSource, setIsImportingSource] = useState(false);

  const applyDraft = useCallback((draft: SubmissionDraftValues) => {
    setSubmissionMode(draft.submissionMode);
    setEditingSubmissionId(draft.editingSubmissionId);
    setEditingSubmissionType(draft.editingSubmissionType);
    setLockedServerName(draft.lockedServerName);
    setLockedVersion(draft.lockedVersion);
    setSourceMode(draft.sourceMode);
    setRepositoryUrl(draft.repositoryUrl);
    setRepositorySubfolder(draft.repositorySubfolder);
    setName(draft.name);
    setIsNameOverrideEnabled(draft.isNameOverrideEnabled);
    setTitle(draft.title);
    setVersion(draft.version);
    setDescription(draft.description);
    setDocumentation(draft.documentation);
    setWebsiteUrl(draft.websiteUrl);
    setCategory(draft.category);
    setServerMeta(draft.serverMeta);
    setIconUrl(draft.iconUrl);
    setRemotes(draft.remotes);
    setPackages(draft.packages);
    setOwnerOrganizationId(draft.ownerOrganizationId);
    setSourceImportMessage(draft.sourceImportMessage);
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
            const version =
              requestedVersion === "new"
                ? (versions.find((item) => item.isLatest) ?? versions[0])
                : (versions.find((item) => item.version === requestedVersion) ??
                  versions.find((item) => item.isLatest) ??
                  versions[0]);
            if (!version) {
              setError("Server version could not be loaded.");
              return;
            }
            applyDraft(publishedServerDraftValues(response, version, requestedMode));
          })
          .catch((caught) => {
            setError(caught instanceof Error ? caught.message : "Server could not be loaded.");
          })
          .finally(() => setIsLoadingSubmission(false));
        return;
      }

      const requestedMode: SubmissionMode =
        searchParams.get("version") === "new" ? "new_version" : "edit";
      setIsLoadingSubmission(true);
      setError("");
      getSubmission(submissionId)
        .then((submission) => {
          if (submission.status === "published" && requestedMode !== "new_version") {
            setError("Published submissions cannot be edited. Add a new version instead.");
            return;
          }
          applyDraft(submissionDraftValues(submission, requestedMode));
        })
        .catch((caught) => {
          setError(caught instanceof Error ? caught.message : "Submission could not be loaded.");
        })
        .finally(() => setIsLoadingSubmission(false));
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [applyDraft, setError]);

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
      const metadataRepository = recordValue(metadata.repository) ?? {};
      const metadataRepositoryReference = normalizeRepositoryReference(
        stringValue(metadataRepository.url) || repositoryReference,
      );
      const metadataPackages = importedPackages(metadata.packages);
      const metadataRemotes = importedRemotes(metadata.remotes);
      const metadataIconUrl = firstIconUrlFromMetadata(metadata);

      setSourceMode("repository");
      setRepositoryUrl(metadataRepositoryReference);
      setRepositorySubfolder(stringValue(metadataRepository.subfolder) || repositorySubfolder);
      setName(metadata.name || "");
      setTitle(metadata.title || "");
      setVersion("1.0.0");
      setDescription(metadata.description || "");
      setDocumentation(metadata.documentation || "");
      setWebsiteUrl(metadata.websiteUrl || repositoryWebUrl(metadataRepositoryReference));
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

  return {
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
  };
}
