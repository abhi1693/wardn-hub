import { Buffer } from 'node:buffer';
import { setTimeout as delay } from 'node:timers/promises';

import type {
  SkillAuditResult,
  SkillAuditSummary,
  SkillSearchItem,
  SkillSearchResult,
  WardnBundle,
  WardnBundleFile,
  WardnSkillRoot,
} from './types.js';
import {
  decodeBase64,
  encodeSkillId,
  validateBundleText,
  validateBundlePath,
  validateHash,
  validateRootSkill,
} from './validation.js';

const DEFAULT_API_BASE_URL = 'https://hub.wardnai.dev/api/v1';
const MAX_RESPONSE_BYTES = 48 * 1024 * 1024;
const MAX_DETAIL_RESPONSE_BYTES = 512 * 1024;
const MAX_AUDIT_RESPONSE_BYTES = 4 * 1024 * 1024;
const MAX_FILE_BYTES = 8 * 1024 * 1024;
const MAX_BUNDLE_BYTES = 16 * 1024 * 1024;
const MAX_BUNDLE_FILES = 256;
const REQUEST_RETRY_DELAYS_MS = [200, 800] as const;
const AUDIT_TIME_PATTERN = /^(?<whole>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.(?<fraction>[0-9]{1,9}))?(?:Z|\+00:00)$/;
const OWNER_PATTERN = /^[A-Za-z0-9._-]+$/;
const SKILL_SLUG_PATTERN = /^[a-z0-9]+(?:[-_][a-z0-9]+)*$/;
const TRANSIENT_REQUEST_ERROR_CODES = new Set([
  'EAI_AGAIN',
  'ECONNABORTED',
  'ECONNREFUSED',
  'ECONNRESET',
  'EHOSTDOWN',
  'EHOSTUNREACH',
  'ENETDOWN',
  'ENETRESET',
  'ENETUNREACH',
  'ENOTFOUND',
  'ETIMEDOUT',
  'UND_ERR_CONNECT_TIMEOUT',
  'UND_ERR_HEADERS_TIMEOUT',
  'UND_ERR_SOCKET',
]);

type FetchImplementation = typeof fetch;

export interface HubClientOptions {
  apiBaseUrl?: string;
  fetchImplementation?: FetchImplementation;
  timeoutMs?: number;
  version: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isInteger(value: unknown, minimum = 0): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= minimum;
}

function codePoints(value: string): string[] {
  return [...value];
}

function truncate(value: string, length: number): string {
  return codePoints(value).slice(0, length).join('');
}

function requestErrorChain(error: unknown): unknown[] {
  const pending = [error];
  const visited = new Set<unknown>();
  const chain: unknown[] = [];
  while (pending.length > 0) {
    const current = pending.shift();
    if (current === undefined || visited.has(current)) continue;
    visited.add(current);
    chain.push(current);
    if (isRecord(current)) {
      if (current.cause !== undefined) pending.push(current.cause);
      if (Array.isArray(current.errors)) pending.push(...current.errors);
    }
  }
  return chain;
}

function requestErrorCodes(error: unknown): string[] {
  return [
    ...new Set(
      requestErrorChain(error)
        .map((item) => (isRecord(item) && typeof item.code === 'string' ? item.code : null))
        .filter((code): code is string => code !== null),
    ),
  ];
}

function isRetryableRequestError(error: unknown): boolean {
  const chain = requestErrorChain(error);
  if (
    chain.some(
      (item) =>
        item instanceof Error && (item.name === 'AbortError' || item.name === 'TimeoutError'),
    )
  ) {
    return false;
  }
  const codes = requestErrorCodes(error);
  if (codes.length > 0) {
    return codes.some((code) => TRANSIENT_REQUEST_ERROR_CODES.has(code));
  }
  if (chain.some((item) => item instanceof Error && /redirect/i.test(item.message))) {
    return false;
  }
  return error instanceof TypeError && error.message === 'fetch failed';
}

function describeRequestError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  const codes = requestErrorCodes(error);
  return codes.length === 0 ? message : `${message} (${codes.join(', ')})`;
}

function rankForScore(score: number): SkillAuditSummary['rank'] {
  if (score >= 99) return 'S';
  if (score >= 88) return 'A+';
  if (score >= 75) return 'A';
  if (score >= 63) return 'A-';
  if (score >= 50) return 'B+';
  if (score >= 38) return 'B';
  if (score >= 25) return 'B-';
  if (score >= 13) return 'C+';
  return 'C';
}

async function readBoundedJson(response: Response, maximumBytes: number): Promise<unknown> {
  if (response.body === null) {
    throw new Error('Wardn Hub returned an empty response');
  }
  const contentLength = Number(response.headers.get('content-length'));
  if (Number.isFinite(contentLength) && contentLength > maximumBytes) {
    throw new Error('Wardn Hub response exceeded the download limit');
  }

  const reader = response.body.getReader();
  const chunks: Buffer[] = [];
  let totalBytes = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    totalBytes += value.byteLength;
    if (totalBytes > maximumBytes) {
      await reader.cancel();
      throw new Error('Wardn Hub response exceeded the download limit');
    }
    chunks.push(Buffer.from(value));
  }

  try {
    const decoded = new TextDecoder('utf-8', { fatal: true }).decode(
      Buffer.concat(chunks, totalBytes),
    );
    return JSON.parse(decoded) as unknown;
  } catch {
    throw new Error('Wardn Hub returned invalid JSON');
  }
}

function decodeBundleFile(value: unknown): WardnBundleFile {
  if (!isRecord(value)) {
    throw new Error('Wardn Hub returned an invalid bundle file');
  }
  const { path, contents } = value;
  const encoding = value.encoding ?? 'utf-8';
  const executable = value.executable ?? false;
  if (
    typeof path !== 'string' ||
    typeof contents !== 'string' ||
    (encoding !== 'utf-8' && encoding !== 'base64') ||
    typeof executable !== 'boolean'
  ) {
    throw new Error('Wardn Hub returned an invalid bundle file');
  }
  validateBundlePath(path);
  const decoded = encoding === 'base64' ? decodeBase64(contents) : Buffer.from(contents, 'utf8');
  if (decoded.byteLength > MAX_FILE_BYTES) {
    throw new Error(`Wardn bundle file exceeds ${MAX_FILE_BYTES} bytes: ${path}`);
  }
  if (encoding === 'utf-8') validateBundleText(contents);
  if (path === 'SKILL.md') {
    if (encoding !== 'utf-8') {
      throw new Error('Wardn SKILL.md must use UTF-8 encoding');
    }
    validateRootSkill(contents);
  }
  return { path, contents: decoded, encoding, executable };
}

function validateSkillPackage(payload: Record<string, unknown>): string {
  if (payload.bundleFormatVersion !== 2) {
    throw new Error('Wardn skill package must be refreshed to bundle format 2');
  }
  if (payload.resolutionStatus !== 'complete') {
    const issues = Array.isArray(payload.resolutionIssues) ? payload.resolutionIssues : [];
    const first = issues.find(isRecord);
    const reason = first && typeof first.reason === 'string' ? `: ${truncate(first.reason, 240)}` : '';
    throw new Error(`Wardn skill package is ${String(payload.resolutionStatus ?? 'unresolved')}${reason}`);
  }
  if (
    typeof payload.sourceEntrypoint !== 'string' ||
    payload.sourceEntrypoint.length === 0 ||
    payload.sourceEntrypoint.length > 2048
  ) {
    throw new Error('Wardn skill package has an invalid source entrypoint');
  }
  validateBundlePath(payload.sourceEntrypoint);
  return payload.sourceEntrypoint;
}

function validateSearchItem(value: unknown): SkillSearchItem {
  if (!isRecord(value)) {
    throw new Error('Wardn skill search response failed validation');
  }
  const {
    id,
    slug,
    source,
    name,
    description,
    isOfficial,
    auditStatus,
    auditScore,
    auditRank,
    installs,
    url,
    sourceUrl,
  } = value;
  if (
    typeof id !== 'string' ||
    id.length === 0 ||
    id.length > 768 ||
    typeof slug !== 'string' ||
    !SKILL_SLUG_PATTERN.test(slug) ||
    typeof source !== 'string' ||
    source.length === 0 ||
    source.length > 300 ||
    id !== `${source}/${slug}` ||
    typeof name !== 'string' ||
    name.length === 0 ||
    name.length > 200 ||
    typeof description !== 'string' ||
    typeof isOfficial !== 'boolean' ||
    (auditStatus !== null &&
      auditStatus !== 'pass' &&
      auditStatus !== 'warn' &&
      auditStatus !== 'fail') ||
    (auditScore !== null && (!isInteger(auditScore) || auditScore > 100)) ||
    (auditRank !== null &&
      !['S', 'A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C'].includes(String(auditRank))) ||
    ((auditStatus === null) !== (auditScore === null)) ||
    ((auditStatus === null) !== (auditRank === null)) ||
    !isInteger(installs) ||
    typeof url !== 'string' ||
    url.length > 2048 ||
    !/^https:\/\/[^\s]+$/.test(url) ||
    (sourceUrl !== null && (typeof sourceUrl !== 'string' || sourceUrl.length > 2048))
  ) {
    throw new Error('Wardn skill search response failed validation');
  }
  if (auditScore !== null && auditRank !== rankForScore(auditScore)) {
    throw new Error('Wardn skill search response failed validation');
  }
  encodeSkillId(id);
  return {
    id,
    name,
    description: truncate(description, 500),
    source,
    isOfficial,
    auditStatus,
    auditScore,
    auditRank: auditRank as SkillSearchItem['auditRank'],
    installs,
    url,
    sourceUrl,
  };
}

function validateAuditTimestamp(value: string): void {
  if (!AUDIT_TIME_PATTERN.test(value)) {
    throw new Error('Wardn skill audit response failed validation');
  }
}

interface ValidatedAudit extends Omit<SkillAuditSummary, 'summaryTruncated'> {
  originalSummary: string;
}

function validateAudit(value: unknown): ValidatedAudit {
  if (!isRecord(value)) {
    throw new Error('Wardn skill audit response failed validation');
  }
  const {
    scannerName,
    scannerVersion,
    policyName,
    policyVersion,
    policyFingerprint,
    status,
    summary,
    auditedAt,
    riskLevel,
    categories,
    score,
    rank,
    scoreDeductions,
  } = value;
  if (
    typeof scannerName !== 'string' ||
    scannerName.length === 0 ||
    scannerName.length > 120 ||
    typeof scannerVersion !== 'string' ||
    scannerVersion.length === 0 ||
    scannerVersion.length > 32 ||
    typeof policyName !== 'string' ||
    policyName.length === 0 ||
    policyName.length > 120 ||
    typeof policyVersion !== 'string' ||
    policyVersion.length > 32 ||
    typeof policyFingerprint !== 'string' ||
    !/^(?:|[a-f0-9]{64})$/.test(policyFingerprint) ||
    (status !== 'pass' && status !== 'warn' && status !== 'fail') ||
    typeof summary !== 'string' ||
    typeof auditedAt !== 'string' ||
    !['low', 'medium', 'high', 'critical'].includes(String(riskLevel)) ||
    (categories !== null &&
      (!Array.isArray(categories) ||
        categories.length > 500 ||
        categories.some((category) => typeof category !== 'string' || category.length > 256))) ||
    !isInteger(score) ||
    score > 100 ||
    !['S', 'A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C'].includes(String(rank)) ||
    rank !== rankForScore(score) ||
    !Array.isArray(scoreDeductions) ||
    scoreDeductions.length > 500 ||
    scoreDeductions.some(
      (deduction) =>
        !isRecord(deduction) ||
        typeof deduction.category !== 'string' ||
        deduction.category.length > 256 ||
        !isInteger(deduction.points) ||
        deduction.points > 100 ||
        !isInteger(deduction.findingCount) ||
        typeof deduction.maxSeverity !== 'string' ||
        !['safe', 'info', 'low', 'medium', 'high', 'critical'].includes(
          deduction.maxSeverity,
        ),
    )
  ) {
    throw new Error('Wardn skill audit response failed validation');
  }
  const expectedStatus =
    riskLevel === 'low' ? 'pass' : riskLevel === 'medium' ? 'warn' : 'fail';
  const scoreCap =
    riskLevel === 'medium' ? 79 : riskLevel === 'high' ? 49 : riskLevel === 'critical' ? 24 : 100;
  if (status !== expectedStatus || score > scoreCap) {
    throw new Error('Wardn skill audit response failed validation');
  }
  validateAuditTimestamp(auditedAt);
  return {
    scannerName,
    scannerVersion,
    policyName,
    policyVersion,
    policyFingerprint,
    status,
    summary: truncate(summary.replace(/[\r\n\t]/g, ' '), 240),
    originalSummary: summary,
    auditedAt,
    riskLevel: riskLevel as SkillAuditSummary['riskLevel'],
    categories,
    score,
    rank: rank as SkillAuditSummary['rank'],
    scoreDeductions: scoreDeductions as SkillAuditSummary['scoreDeductions'],
  };
}

export class HubClient {
  readonly apiBaseUrl: string;
  readonly version: string;
  readonly #fetch: FetchImplementation;
  readonly #timeoutMs: number;

  constructor(options: HubClientOptions) {
    const configuredBaseUrl = options.apiBaseUrl ?? DEFAULT_API_BASE_URL;
    const baseUrl = new URL(configuredBaseUrl);
    if (
      (baseUrl.protocol !== 'https:' &&
        baseUrl.hostname !== 'localhost' &&
        baseUrl.hostname !== '127.0.0.1') ||
      baseUrl.username.length > 0 ||
      baseUrl.password.length > 0 ||
      baseUrl.search.length > 0 ||
      baseUrl.hash.length > 0
    ) {
      throw new Error('Wardn Hub API URL must use HTTPS');
    }
    this.apiBaseUrl = baseUrl.toString().replace(/\/$/, '');
    this.version = options.version;
    this.#fetch = options.fetchImplementation ?? fetch;
    this.#timeoutMs = options.timeoutMs ?? 60_000;
  }

  async #requestJson(
    url: URL,
    label: string,
    maximumBytes: number,
    timeoutMs: number,
  ): Promise<{ response: Response; payload?: unknown }> {
    const requestTimeoutMs = Math.min(this.#timeoutMs, timeoutMs);
    const deadline = Date.now() + requestTimeoutMs;
    let attempt = 0;
    while (true) {
      attempt += 1;
      try {
        const response = await this.#fetch(url, {
          headers: {
            accept: 'application/json',
            'user-agent': `@wardn-ai/skills/${this.version}`,
          },
          redirect: 'error',
          signal: AbortSignal.timeout(Math.max(1, deadline - Date.now())),
        });
        if (!response.ok) return { response };
        return { response, payload: await readBoundedJson(response, maximumBytes) };
      } catch (error) {
        const retryDelay = REQUEST_RETRY_DELAYS_MS[attempt - 1];
        const canRetry =
          retryDelay !== undefined &&
          isRetryableRequestError(error) &&
          Date.now() + retryDelay < deadline;
        if (!canRetry) {
          const attempts = attempt === 1 ? '' : ` after ${attempt} attempts`;
          throw new Error(`${label} failed${attempts}: ${describeRequestError(error)}`, {
            cause: error,
          });
        }
        await delay(retryDelay);
      }
    }
  }

  async search(query: string, owner?: string, limit = 8): Promise<SkillSearchResult> {
    const normalizedQuery = query.trim();
    if (normalizedQuery.length < 2 || normalizedQuery.length > 200) {
      throw new Error('search query must contain between 2 and 200 characters');
    }
    if (!isInteger(limit, 1) || limit > 200) {
      throw new Error('search limit must be between 1 and 200');
    }
    if (
      owner !== undefined &&
      (owner.length === 0 || owner.length > 200 || !OWNER_PATTERN.test(owner))
    ) {
      throw new Error('search owner is invalid');
    }
    const url = new URL(`${this.apiBaseUrl}/skills/search`);
    url.searchParams.set('q', normalizedQuery);
    url.searchParams.set('limit', String(limit));
    if (owner !== undefined) url.searchParams.set('owner', owner);
    const { response, payload } = await this.#requestJson(
      url,
      'Wardn skill search',
      MAX_DETAIL_RESPONSE_BYTES,
      15_000,
    );
    if (!response.ok) {
      throw new Error(`Wardn skill search returned HTTP ${response.status}`);
    }
    if (
      !isRecord(payload) ||
      typeof payload.query !== 'string' ||
      typeof payload.searchType !== 'string' ||
      typeof payload.auditEnabled !== 'boolean' ||
      !isInteger(payload.count) ||
      typeof payload.durationMs !== 'number' ||
      !Number.isFinite(payload.durationMs) ||
      payload.durationMs < 0 ||
      !Array.isArray(payload.data) ||
      payload.count !== payload.data.length
    ) {
      throw new Error('Wardn skill search response failed validation');
    }
    const data = payload.data.map(validateSearchItem);
    return {
      auditEnabled: payload.auditEnabled,
      query: payload.query,
      count: payload.count,
      data,
    };
  }

  async audit(id: string): Promise<SkillAuditResult> {
    const encodedId = encodeSkillId(id);
    const url = new URL(`${this.apiBaseUrl}/skills/audit/${encodedId}`);
    const { response, payload } = await this.#requestJson(
      url,
      'Wardn skill audit request',
      MAX_AUDIT_RESPONSE_BYTES,
      15_000,
    );
    if (response.status === 404) return { id, auditStatus: 'unaudited' };
    if (!response.ok) {
      throw new Error(`Wardn skill audit returned HTTP ${response.status}`);
    }
    if (
      !isRecord(payload) ||
      payload.id !== id ||
      typeof payload.contentHash !== 'string' ||
      !isRecord(payload.audit)
    ) {
      throw new Error('Wardn skill audit response failed validation');
    }
    const contentHash = validateHash(payload.contentHash);
    const audit = validateAudit(payload.audit);
    const currentAudit = {
      scannerName: audit.scannerName,
      scannerVersion: audit.scannerVersion,
      policyName: audit.policyName,
      policyVersion: audit.policyVersion,
      policyFingerprint: audit.policyFingerprint,
      status: audit.status,
      riskLevel: audit.riskLevel,
      auditedAt: audit.auditedAt,
      categories: audit.categories,
      summary: audit.summary,
      summaryTruncated: codePoints(audit.originalSummary).length > 240,
      score: audit.score,
      rank: audit.rank,
      scoreDeductions: audit.scoreDeductions,
    };
    return {
      id,
      contentHash,
      audit: currentAudit,
    };
  }

  async fetchRoot(id: string): Promise<WardnSkillRoot> {
    const encodedId = encodeSkillId(id);
    const url = new URL(`${this.apiBaseUrl}/skills/${encodedId}`);
    const { response, payload } = await this.#requestJson(
      url,
      'Wardn skill detail request',
      MAX_DETAIL_RESPONSE_BYTES,
      15_000,
    );
    if (!response.ok) {
      throw new Error(`Wardn skill detail returned HTTP ${response.status}`);
    }
    if (
      !isRecord(payload) ||
      payload.id !== id ||
      typeof payload.hash !== 'string' ||
      !Array.isArray(payload.files) ||
      payload.files.length !== 1
    ) {
      throw new Error('Wardn skill detail failed validation');
    }
    const sourceEntrypoint = validateSkillPackage(payload);
    const fileValue = payload.files[0];
    if (!isRecord(fileValue) || fileValue.path !== 'SKILL.md' || typeof fileValue.contents !== 'string') {
      throw new Error('Wardn skill detail failed validation');
    }
    const file = decodeBundleFile(fileValue);
    if (file.encoding !== 'utf-8') {
      throw new Error('Wardn skill detail failed validation');
    }
    const contents = fileValue.contents;
    return {
      id,
      hash: validateHash(payload.hash),
      characters: codePoints(contents).length,
      contents,
      sourceEntrypoint,
    };
  }

  async fetchBundle(id: string, expectedHash?: string): Promise<WardnBundle> {
    const encodedId = encodeSkillId(id);
    if (expectedHash !== undefined) validateHash(expectedHash, 'expected hash');
    const url = new URL(`${this.apiBaseUrl}/skills/${encodedId}`);
    url.searchParams.set('include_bundle', 'true');
    const { response, payload } = await this.#requestJson(
      url,
      'Wardn skill download',
      MAX_RESPONSE_BYTES,
      60_000,
    );
    if (!response.ok) {
      throw new Error(`Wardn skill download returned HTTP ${response.status}`);
    }
    if (!isRecord(payload) || payload.id !== id || typeof payload.hash !== 'string') {
      throw new Error('Wardn Hub returned an invalid bundle identity');
    }
    const sourceEntrypoint = validateSkillPackage(payload);
    const hash = validateHash(payload.hash);
    if (expectedHash !== undefined && hash !== expectedHash) {
      throw new Error('Wardn skill changed since the expected hash was selected');
    }
    if (
      !Array.isArray(payload.files) ||
      payload.files.length === 0 ||
      payload.files.length > MAX_BUNDLE_FILES
    ) {
      throw new Error('Wardn Hub returned an invalid bundle file count');
    }

    const paths = new Set<string>();
    let totalBytes = 0;
    const files = payload.files.map((fileValue) => {
      const decoded = decodeBundleFile(fileValue);
      if (decoded.path === '.wardn-skill.json') {
        throw new Error('Wardn bundle contains the reserved installation marker');
      }
      if (paths.has(decoded.path)) {
        throw new Error(`Wardn bundle contains a duplicate path: ${decoded.path}`);
      }
      paths.add(decoded.path);
      totalBytes += decoded.contents.byteLength;
      if (totalBytes > MAX_BUNDLE_BYTES) {
        throw new Error(`Wardn bundle exceeds ${MAX_BUNDLE_BYTES} decoded bytes`);
      }
      return decoded;
    });
    if (!paths.has('SKILL.md')) {
      throw new Error('Wardn bundle does not contain a root SKILL.md');
    }
    if (!paths.has(sourceEntrypoint)) {
      throw new Error('Wardn bundle does not contain its source entrypoint');
    }
    return { id, hash, sourceEntrypoint, files };
  }

  async recordInstall(id: string, contentHash: string): Promise<void> {
    const encodedId = encodeSkillId(id);
    validateHash(contentHash);
    const url = new URL(`${this.apiBaseUrl}/skills/telemetry/${encodedId}`);
    url.searchParams.set('content_hash', contentHash);
    url.searchParams.set('resolver_version', this.version);
    url.searchParams.set('client', 'wardn-cli');
    try {
      await this.#fetch(url, {
        method: 'POST',
        headers: { 'user-agent': `@wardn-ai/skills/${this.version}` },
        redirect: 'error',
        signal: AbortSignal.timeout(5_000),
      });
    } catch {
      // Telemetry is best-effort and must never affect skill installation.
    }
  }
}

export function telemetryDisabled(environment: NodeJS.ProcessEnv = process.env): boolean {
  return Boolean(
    environment.WARDN_HUB_DISABLE_TELEMETRY ||
      environment.DISABLE_TELEMETRY ||
      environment.DO_NOT_TRACK,
  );
}
