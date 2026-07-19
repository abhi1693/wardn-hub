export interface WardnBundleFile {
  path: string;
  contents: Buffer;
  encoding: 'utf-8' | 'base64';
  executable: boolean;
}

export interface WardnBundle {
  id: string;
  hash: string;
  files: WardnBundleFile[];
}

export interface WardnSkillRoot {
  id: string;
  hash: string;
  characters: number;
  contents: string;
}

export interface SkillSearchItem {
  id: string;
  name: string;
  description: string;
  source: string;
  isOfficial: boolean;
  auditStatus: 'pass' | 'warn' | 'fail' | null;
  installs: number;
  url: string;
  sourceUrl: string | null;
}

export interface SkillSearchResult {
  query: string;
  count: number;
  data: SkillSearchItem[];
}

export interface SkillAuditSummary {
  slug: string;
  provider: string;
  status: 'pass' | 'warn' | 'fail';
  riskLevel: string | null;
  auditedAt: string;
  categories: string[] | null;
  summary: string;
  summaryTruncated: boolean;
}

export interface AuditedSkillResult {
  id: string;
  contentHash: string;
  hardRejectCount: number;
  warningCount: number;
  failureCount: number;
  latestAudits: SkillAuditSummary[];
}

export interface UnauditedSkillResult {
  id: string;
  auditStatus: 'unaudited';
}

export type SkillAuditResult = AuditedSkillResult | UnauditedSkillResult;

export interface TemporaryBundleManifest {
  id: string;
  hash: string;
  directory: string;
  fileCount: number;
  decodedBytes: number;
  files: Array<{
    path: string;
    encoding: 'utf-8' | 'base64';
    executable: boolean;
  }>;
}

export interface WardnInstallMarker {
  schemaVersion: 1;
  id: string;
  contentHash: string;
}

export type InstallStatus = 'installed' | 'updated' | 'unchanged';

export interface InstallResult {
  status: InstallStatus;
  id: string;
  hash: string;
  directory: string;
}

export interface ManagedInstallation {
  marker: WardnInstallMarker;
  directory: string;
  skillsDirectory: string;
}

export type InstallScope = 'project' | 'global';

export interface AgentConfig {
  name: string;
  displayName: string;
  projectSkillsDirectory: string;
  globalSkillsDirectory: () => string;
  detectionDirectories: () => string[];
}
