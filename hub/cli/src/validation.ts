import { Buffer } from 'node:buffer';
import { parseDocument } from 'yaml';

const HASH_PATTERN = /^[a-f0-9]{64}$/;
const ID_SEGMENT_PATTERN = /^[A-Za-z0-9._-]+$/;
const SKILL_SLUG_PATTERN = /^[a-z0-9]+(?:[-_][a-z0-9]+)*$/;
const MAX_ID_LENGTH = 768;
const MAX_PATH_LENGTH = 1024;
const MAX_ROOT_SKILL_BYTES = 64 * 1024;

export function validateHash(value: string, label = 'content hash'): string {
  if (!HASH_PATTERN.test(value)) {
    throw new Error(`${label} must be a 64-character lowercase SHA-256 value`);
  }
  return value;
}

export function validateSkillId(value: string): string[] {
  const segments = value.split('/');
  if (
    value.length === 0 ||
    value.length > MAX_ID_LENGTH ||
    segments.length < 2 ||
    segments.length > 8 ||
    segments.some(
      (segment) =>
        segment.length === 0 ||
        segment.length > 200 ||
        segment === '.' ||
        segment === '..' ||
        !ID_SEGMENT_PATTERN.test(segment),
    )
  ) {
    throw new Error('invalid Wardn skill ID');
  }
  const slug = segments.at(-1);
  if (slug === undefined || !SKILL_SLUG_PATTERN.test(slug)) {
    throw new Error('Wardn skill ID must end in a lowercase skill slug');
  }
  return segments;
}

export function encodeSkillId(value: string): string {
  return validateSkillId(value).map(encodeURIComponent).join('/');
}

export function skillSlug(value: string): string {
  const slug = validateSkillId(value).at(-1);
  if (slug === undefined) {
    throw new Error('invalid Wardn skill ID');
  }
  return slug;
}

export function validateSkillSelector(value: string): void {
  if (value.includes('/')) {
    validateSkillId(value);
    return;
  }
  if (!SKILL_SLUG_PATTERN.test(value)) {
    throw new Error(`invalid skill selector: ${value}`);
  }
}

export function validateBundlePath(value: string): string {
  if (
    value.length === 0 ||
    value.length > MAX_PATH_LENGTH ||
    value.startsWith('/') ||
    value.endsWith('/') ||
    value.includes('\\') ||
    value.includes('\0') ||
    hasUnsafePathCharacters(value)
  ) {
    throw new Error(`invalid Wardn bundle path: ${JSON.stringify(value)}`);
  }
  const segments = value.split('/');
  if (
    segments.length > 64 ||
    segments.some(
      (segment) =>
        segment.length === 0 ||
        segment === '.' ||
        segment === '..' ||
        segment.includes(':') ||
        segment.endsWith('.') ||
        segment.endsWith(' ') ||
        /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(segment) ||
        Buffer.byteLength(segment, 'utf8') > 255,
    )
  ) {
    throw new Error(`unsafe Wardn bundle path: ${JSON.stringify(value)}`);
  }
  return value;
}

export function decodeBase64(value: string): Buffer {
  if (
    value.length % 4 !== 0 ||
    !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(
      value,
    )
  ) {
    throw new Error('Wardn bundle contains invalid base64 data');
  }
  const decoded = Buffer.from(value, 'base64');
  if (decoded.toString('base64') !== value) {
    throw new Error('Wardn bundle contains non-canonical base64 data');
  }
  return decoded;
}

function hasUnsafeTextCharacters(value: string): boolean {
  for (const character of value) {
    const codePoint = character.codePointAt(0);
    if (codePoint === undefined) continue;
    if (
      (codePoint < 32 && codePoint !== 9 && codePoint !== 10 && codePoint !== 13) ||
      (codePoint >= 127 && codePoint <= 159) ||
      codePoint === 0x061c ||
      codePoint === 0x200e ||
      codePoint === 0x200f ||
      (codePoint >= 0x202a && codePoint <= 0x202e) ||
      (codePoint >= 0x2066 && codePoint <= 0x2069)
    ) {
      return true;
    }
  }
  return false;
}

function hasUnsafePathCharacters(value: string): boolean {
  for (const character of value) {
    const codePoint = character.codePointAt(0);
    if (codePoint === undefined) continue;
    if (
      codePoint < 32 ||
      (codePoint >= 127 && codePoint <= 159) ||
      codePoint === 0x061c ||
      codePoint === 0x200e ||
      codePoint === 0x200f ||
      (codePoint >= 0x202a && codePoint <= 0x202e) ||
      (codePoint >= 0x2066 && codePoint <= 0x2069)
    ) {
      return true;
    }
  }
  return false;
}

export function validateBundleText(contents: string): void {
  if (hasUnsafeTextCharacters(contents)) {
    throw new Error('Wardn bundle contains unsafe text characters');
  }
}

export function validateRootSkill(contents: string): void {
  const byteLength = Buffer.byteLength(contents, 'utf8');
  if (
    byteLength === 0 ||
    byteLength > MAX_ROOT_SKILL_BYTES ||
    hasUnsafeTextCharacters(contents)
  ) {
    throw new Error('Wardn SKILL.md failed text validation');
  }

  const normalized = contents.startsWith('\uFEFF') ? contents.slice(1) : contents;
  if (/\r(?!\n)/.test(normalized)) {
    throw new Error('Wardn SKILL.md contains unsupported line endings');
  }
  const match = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/.exec(normalized);
  if (match?.[1] === undefined) {
    throw new Error('Wardn SKILL.md must contain YAML frontmatter');
  }
  const document = parseDocument(match[1], {
    schema: 'core',
    uniqueKeys: true,
  });
  if (document.errors.length > 0) {
    throw new Error('Wardn SKILL.md contains invalid YAML frontmatter');
  }
  const frontmatter: unknown = document.toJS({ maxAliasCount: 0 });
  if (
    typeof frontmatter !== 'object' ||
    frontmatter === null ||
    Array.isArray(frontmatter)
  ) {
    throw new Error('Wardn SKILL.md frontmatter must be a mapping');
  }
  const metadata = frontmatter as Record<string, unknown>;
  if (
    typeof metadata.name !== 'string' ||
    metadata.name.trim().length === 0 ||
    typeof metadata.description !== 'string' ||
    metadata.description.trim().length === 0
  ) {
    throw new Error('Wardn SKILL.md requires non-empty name and description fields');
  }
  if (normalized.slice(match[0].length).trim().length === 0) {
    throw new Error('Wardn SKILL.md requires a non-empty instruction body');
  }
}
