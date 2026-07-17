import assert from 'node:assert/strict';
import { lstat, mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, test } from 'node:test';

import {
  findManagedInstallations,
  installBundle,
  materializeTemporaryBundle,
  readInstallMarker,
  removeManagedInstallation,
} from '../dist/index.js';

const temporaryDirectories = [];

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) =>
      rm(directory, { recursive: true, force: true }),
    ),
  );
});

async function temporaryDirectory() {
  const directory = await mkdtemp(join(tmpdir(), 'wardn-cli-test.'));
  temporaryDirectories.push(directory);
  return directory;
}

function bundle(hashCharacter, body = '# Weather\n') {
  return {
    id: 'acme/skills/weather',
    hash: hashCharacter.repeat(64),
    files: [
      {
        path: 'SKILL.md',
        contents: Buffer.from(
          `---\nname: weather\ndescription: Check weather.\n---\n\n${body}`,
        ),
        executable: false,
      },
      {
        path: 'scripts/run.sh',
        contents: Buffer.from('#!/bin/sh\n'),
        executable: true,
      },
    ],
  };
}

test('installBundle installs, leaves unchanged snapshots alone, and updates atomically', async () => {
  const root = await temporaryDirectory();
  const skillsDirectory = join(root, 'skills');

  const installed = await installBundle(bundle('a'), skillsDirectory);
  assert.equal(installed.status, 'installed');
  assert.deepEqual(await readInstallMarker(installed.directory), {
    schemaVersion: 1,
    id: 'acme/skills/weather',
    contentHash: 'a'.repeat(64),
  });

  const unchanged = await installBundle(bundle('a'), skillsDirectory);
  assert.equal(unchanged.status, 'unchanged');

  const updated = await installBundle(bundle('b', '# Updated\n'), skillsDirectory);
  assert.equal(updated.status, 'updated');
  assert.match(await readFile(join(updated.directory, 'SKILL.md'), 'utf8'), /# Updated/);
  assert.equal((await readInstallMarker(updated.directory)).contentHash, 'b'.repeat(64));
});

test('installBundle refuses unmanaged collisions and different Wardn IDs', async () => {
  const root = await temporaryDirectory();
  const skillsDirectory = join(root, 'skills');
  const target = join(skillsDirectory, 'weather');
  await mkdir(target, { recursive: true });
  await writeFile(join(target, 'SKILL.md'), '# User managed\n');

  await assert.rejects(
    () => installBundle(bundle('a'), skillsDirectory),
    /not installed by Wardn/,
  );

  await writeFile(
    join(target, '.wardn-skill.json'),
    JSON.stringify({
      schemaVersion: 1,
      id: 'other/skills/weather',
      contentHash: 'c'.repeat(64),
    }),
  );
  await assert.rejects(
    () => installBundle(bundle('a'), skillsDirectory),
    /slug collision/,
  );
});

test('managed installations can be selected and removed without touching unmanaged skills', async () => {
  const root = await temporaryDirectory();
  const skillsDirectory = join(root, 'skills');
  const installed = await installBundle(bundle('a'), skillsDirectory);
  const unmanaged = join(skillsDirectory, 'unmanaged');
  await mkdir(unmanaged);
  await writeFile(join(unmanaged, 'SKILL.md'), '# Unmanaged\n');

  const installations = await findManagedInstallations([skillsDirectory], ['weather']);
  assert.equal(installations.length, 1);
  assert.equal(installations[0].directory, installed.directory);

  await removeManagedInstallation(installations[0]);

  await assert.rejects(() => readFile(join(installed.directory, 'SKILL.md')), /ENOENT/);
  assert.equal(await readFile(join(unmanaged, 'SKILL.md'), 'utf8'), '# Unmanaged\n');
});

test('materializeTemporaryBundle writes a private bundle without an ownership marker', async () => {
  const manifest = await materializeTemporaryBundle(bundle('a'));
  temporaryDirectories.push(manifest.directory);

  assert.equal(manifest.id, 'acme/skills/weather');
  assert.equal(manifest.fileCount, 2);
  assert.equal(manifest.files[1].encoding, 'utf-8');
  assert.equal((await lstat(manifest.directory)).mode & 0o777, 0o700);
  assert.equal((await lstat(join(manifest.directory, 'SKILL.md'))).mode & 0o777, 0o600);
  assert.equal((await lstat(join(manifest.directory, 'scripts/run.sh'))).mode & 0o777, 0o700);
  await assert.rejects(
    () => readFile(join(manifest.directory, '.wardn-skill.json')),
    /ENOENT/,
  );
});
