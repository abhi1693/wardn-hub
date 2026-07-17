import {
  chmod,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rename,
  rmdir,
  rm,
  writeFile,
} from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, isAbsolute, join, parse, resolve } from 'node:path';

import type {
  InstallResult,
  ManagedInstallation,
  TemporaryBundleManifest,
  WardnBundle,
  WardnInstallMarker,
} from './types.js';
import {
  skillSlug,
  validateBundlePath,
  validateHash,
  validateSkillId,
  validateSkillSelector,
} from './validation.js';

const INSTALL_MARKER = '.wardn-skill.json';
const LEGACY_FIND_SKILLS_MARKER = '.wardn-find-skills.json';
const LEGACY_FIND_SKILLS_ID = 'abhi1693/wardn-hub/find-skills';
const LEGACY_REVISION_PATTERN = /^[0-9a-f]{40}$/;

async function pathExists(path: string): Promise<boolean> {
  try {
    await lstat(path);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false;
    throw error;
  }
}

function parseMarker(value: unknown): WardnInstallMarker {
  if (
    typeof value !== 'object' ||
    value === null ||
    Array.isArray(value) ||
    (value as Record<string, unknown>).schemaVersion !== 1 ||
    typeof (value as Record<string, unknown>).id !== 'string' ||
    typeof (value as Record<string, unknown>).contentHash !== 'string'
  ) {
    throw new Error('installed Wardn skill marker failed validation');
  }
  const marker = value as Record<string, unknown>;
  const id = marker.id as string;
  const contentHash = marker.contentHash as string;
  validateSkillId(id);
  validateHash(contentHash);
  return { schemaVersion: 1, id, contentHash };
}

export async function readInstallMarker(
  targetDirectory: string,
  expectedId?: string,
): Promise<WardnInstallMarker> {
  const targetStat = await lstat(targetDirectory);
  if (!targetStat.isDirectory() || targetStat.isSymbolicLink()) {
    throw new Error(`skill target is not a regular directory: ${targetDirectory}`);
  }
  const markerPath = join(targetDirectory, INSTALL_MARKER);
  let markerStat;
  try {
    markerStat = await lstat(markerPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      throw new Error(`refusing to manage a skill not installed by Wardn: ${targetDirectory}`);
    }
    throw error;
  }
  if (!markerStat.isFile() || markerStat.isSymbolicLink()) {
    throw new Error(`installed Wardn skill marker failed validation: ${markerPath}`);
  }
  if (markerStat.size > 4096) {
    throw new Error(`installed Wardn skill marker is too large: ${markerPath}`);
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(await readFile(markerPath, 'utf8')) as unknown;
  } catch {
    throw new Error(`installed Wardn skill marker failed validation: ${markerPath}`);
  }
  const marker = parseMarker(parsed);
  if (expectedId !== undefined && marker.id !== expectedId) {
    throw new Error(
      `skill slug collision: ${targetDirectory} is managed for ${marker.id}, not ${expectedId}`,
    );
  }
  return marker;
}

async function readLegacyFindSkillsMarker(
  targetDirectory: string,
  expectedId: string,
): Promise<boolean> {
  const markerPath = join(targetDirectory, LEGACY_FIND_SKILLS_MARKER);
  let markerStat;
  try {
    markerStat = await lstat(markerPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false;
    throw error;
  }
  if (!markerStat.isFile() || markerStat.isSymbolicLink() || markerStat.size > 4096) {
    throw new Error(`legacy Wardn skill marker failed validation: ${markerPath}`);
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(await readFile(markerPath, 'utf8')) as unknown;
  } catch {
    throw new Error(`legacy Wardn skill marker failed validation: ${markerPath}`);
  }
  if (
    typeof parsed !== 'object' ||
    parsed === null ||
    Array.isArray(parsed) ||
    (parsed as Record<string, unknown>).schemaVersion !== 1 ||
    (parsed as Record<string, unknown>).repository !== 'abhi1693/wardn-hub' ||
    (parsed as Record<string, unknown>).skill !== 'find-skills' ||
    typeof (parsed as Record<string, unknown>).revision !== 'string' ||
    !LEGACY_REVISION_PATTERN.test((parsed as Record<string, unknown>).revision as string)
  ) {
    throw new Error(`legacy Wardn skill marker failed validation: ${markerPath}`);
  }

  if (LEGACY_FIND_SKILLS_ID !== expectedId) {
    throw new Error(
      `skill slug collision: ${targetDirectory} is managed for ${LEGACY_FIND_SKILLS_ID}, not ${expectedId}`,
    );
  }
  return true;
}

async function secureSkillsDirectory(path: string): Promise<string> {
  if (!isAbsolute(path)) {
    throw new Error('agent skills directory must be an absolute path');
  }
  const resolved = resolve(path);
  if (resolved === parse(resolved).root) {
    throw new Error('agent skills directory must not be the filesystem root');
  }
  await mkdir(resolved, { recursive: true, mode: 0o700 });
  const canonical = await realpath(resolved);
  if (canonical === parse(canonical).root) {
    throw new Error('agent skills directory must not resolve to the filesystem root');
  }
  return canonical;
}

async function writeBundleFiles(bundle: WardnBundle, stagingDirectory: string): Promise<void> {
  for (const file of bundle.files) {
    validateBundlePath(file.path);
    if (file.path === INSTALL_MARKER || file.path === LEGACY_FIND_SKILLS_MARKER) {
      throw new Error('Wardn bundle contains the reserved installation marker');
    }
    const outputPath = resolve(stagingDirectory, file.path);
    if (!outputPath.startsWith(`${stagingDirectory}/`)) {
      throw new Error(`Wardn bundle path escaped the staging directory: ${file.path}`);
    }
    await mkdir(dirname(outputPath), { recursive: true, mode: 0o700 });
    await writeFile(outputPath, file.contents, {
      flag: 'wx',
      mode: file.executable ? 0o700 : 0o600,
    });
  }
}

async function materializeBundle(bundle: WardnBundle, stagingDirectory: string): Promise<void> {
  await writeBundleFiles(bundle, stagingDirectory);
  const marker: WardnInstallMarker = {
    schemaVersion: 1,
    id: bundle.id,
    contentHash: bundle.hash,
  };
  const markerPath = join(stagingDirectory, INSTALL_MARKER);
  await writeFile(markerPath, `${JSON.stringify(marker, null, 2)}\n`, {
    flag: 'wx',
    mode: 0o600,
  });
}

export async function materializeTemporaryBundle(
  bundle: WardnBundle,
): Promise<TemporaryBundleManifest> {
  validateSkillId(bundle.id);
  validateHash(bundle.hash);
  const temporaryRoot = tmpdir();
  if (!isAbsolute(temporaryRoot)) {
    throw new Error('temporary directory must be an absolute path');
  }
  let directory: string | undefined;
  try {
    directory = await mkdtemp(join(temporaryRoot, 'wardn-skill.'));
    await chmod(directory, 0o700);
    await writeBundleFiles(bundle, directory);
    return {
      id: bundle.id,
      hash: bundle.hash,
      directory,
      fileCount: bundle.files.length,
      decodedBytes: bundle.files.reduce(
        (total, file) => total + file.contents.byteLength,
        0,
      ),
      files: bundle.files.map((file) => ({
        path: file.path,
        encoding: file.encoding ?? 'utf-8',
        executable: file.executable,
      })),
    };
  } catch (error) {
    if (directory !== undefined) {
      await rm(directory, { recursive: true, force: true });
    }
    throw error;
  }
}

export async function installBundle(
  bundle: WardnBundle,
  requestedSkillsDirectory: string,
): Promise<InstallResult> {
  validateSkillId(bundle.id);
  validateHash(bundle.hash);
  const skillsDirectory = await secureSkillsDirectory(requestedSkillsDirectory);
  const slug = skillSlug(bundle.id);
  const targetDirectory = join(skillsDirectory, slug);
  const lockDirectory = join(skillsDirectory, `.${slug}.wardn-install.lock`);

  try {
    await mkdir(lockDirectory, { mode: 0o700 });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'EEXIST') {
      throw new Error(`another Wardn skill installation is active for ${slug}`);
    }
    throw error;
  }

  let stagingDirectory: string | undefined;
  let backupDirectory: string | undefined;
  let previousMoved = false;
  try {
    let currentMarker: WardnInstallMarker | undefined;
    let legacyInstallation = false;
    if (await pathExists(targetDirectory)) {
      try {
        currentMarker = await readInstallMarker(targetDirectory, bundle.id);
      } catch (error) {
        if (
          !(error instanceof Error) ||
          !error.message.startsWith('refusing to manage a skill not installed by Wardn')
        ) {
          throw error;
        }
        legacyInstallation = await readLegacyFindSkillsMarker(targetDirectory, bundle.id);
        if (!legacyInstallation) throw error;
      }
    }

    const createdStagingDirectory = await mkdtemp(
      join(skillsDirectory, `.${slug}.stage.`),
    );
    stagingDirectory = createdStagingDirectory;
    await chmod(createdStagingDirectory, 0o700);
    await materializeBundle(bundle, createdStagingDirectory);

    if (currentMarker?.contentHash === bundle.hash) {
      await rm(stagingDirectory, { recursive: true });
      stagingDirectory = undefined;
      return {
        status: 'unchanged',
        id: bundle.id,
        hash: bundle.hash,
        directory: targetDirectory,
      };
    }

    if (currentMarker !== undefined || legacyInstallation) {
      backupDirectory = await mkdtemp(join(skillsDirectory, `.${slug}.backup.`));
      const previousDirectory = join(backupDirectory, 'previous');
      await rename(targetDirectory, previousDirectory);
      previousMoved = true;
      try {
        await rename(stagingDirectory, targetDirectory);
        stagingDirectory = undefined;
        previousMoved = false;
      } catch (error) {
        await rename(previousDirectory, targetDirectory);
        previousMoved = false;
        throw error;
      }
      await rm(backupDirectory, { recursive: true });
      backupDirectory = undefined;
      return {
        status: 'updated',
        id: bundle.id,
        hash: bundle.hash,
        directory: targetDirectory,
      };
    }

    if (await pathExists(targetDirectory)) {
      throw new Error(`skill target appeared during installation: ${targetDirectory}`);
    }
    await rename(stagingDirectory, targetDirectory);
    stagingDirectory = undefined;
    return {
      status: 'installed',
      id: bundle.id,
      hash: bundle.hash,
      directory: targetDirectory,
    };
  } finally {
    if (stagingDirectory !== undefined) {
      await rm(stagingDirectory, { recursive: true, force: true });
    }
    if (previousMoved && backupDirectory !== undefined && !(await pathExists(targetDirectory))) {
      await rename(join(backupDirectory, 'previous'), targetDirectory);
      previousMoved = false;
    }
    if (!previousMoved && backupDirectory !== undefined) {
      await rm(backupDirectory, { recursive: true, force: true });
    }
    await rmdir(lockDirectory).catch((error: NodeJS.ErrnoException) => {
      if (error.code !== 'ENOENT') throw error;
    });
  }
}

function selectorMatches(marker: WardnInstallMarker, selectors: Set<string>): boolean {
  if (selectors.size === 0) return true;
  return selectors.has(marker.id) || selectors.has(skillSlug(marker.id));
}

export async function findManagedInstallations(
  skillsDirectories: string[],
  selectorValues: string[],
): Promise<ManagedInstallation[]> {
  selectorValues.forEach(validateSkillSelector);
  const selectors = new Set(selectorValues);
  const installations = new Map<string, ManagedInstallation>();
  for (const requestedDirectory of [...new Set(skillsDirectories)]) {
    const skillsDirectory = resolve(requestedDirectory);
    let entries;
    try {
      entries = await readdir(skillsDirectory, { withFileTypes: true });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') continue;
      throw error;
    }
    for (const entry of entries) {
      if (!entry.isDirectory() || entry.isSymbolicLink() || entry.name.startsWith('.')) continue;
      const directory = join(skillsDirectory, entry.name);
      try {
        const marker = await readInstallMarker(directory);
        if (selectorMatches(marker, selectors)) {
          installations.set(directory, { marker, directory, skillsDirectory });
        }
      } catch (error) {
        if (
          error instanceof Error &&
          error.message.startsWith('refusing to manage a skill not installed by Wardn')
        ) {
          continue;
        }
        throw error;
      }
    }
  }
  return [...installations.values()].sort((left, right) =>
    left.directory.localeCompare(right.directory),
  );
}

export async function removeManagedInstallation(
  installation: ManagedInstallation,
): Promise<void> {
  const currentMarker = await readInstallMarker(
    installation.directory,
    installation.marker.id,
  );
  if (currentMarker.contentHash !== installation.marker.contentHash) {
    throw new Error(`installed skill changed during removal: ${installation.directory}`);
  }
  await rm(installation.directory, { recursive: true });
}
