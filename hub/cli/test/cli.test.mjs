import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, test } from 'node:test';

import { runCli } from '../dist/cli.js';

let apiBaseUrl;
let currentHash = 'a'.repeat(64);
let telemetryRequests = 0;
let server;
let target;

function payload() {
  return {
    id: 'acme/skills/weather',
    hash: currentHash,
    files: [
      {
        path: 'SKILL.md',
        contents: `---\nname: weather\ndescription: Check weather.\n---\n\n# ${currentHash[0]}\n`,
      },
    ],
  };
}

before(async () => {
  target = await mkdtemp(join(tmpdir(), 'wardn-cli-integration.'));
  server = createServer((request, response) => {
    if (request.method === 'GET' && request.url?.startsWith('/api/v1/skills/search?')) {
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(
        JSON.stringify({
          query: 'weather',
          searchType: 'fuzzy',
          auditEnabled: true,
          count: 1,
          durationMs: 1,
          data: [
            {
              id: 'acme/skills/weather',
              slug: 'weather',
              source: 'acme/skills',
              name: 'Weather',
              description: 'Check weather.',
              isOfficial: false,
              auditStatus: 'pass',
              auditScore: 100,
              auditRank: 'S',
              installs: 3,
              url: 'https://hub.wardnai.dev/skills/acme/skills/weather',
              sourceUrl: 'https://github.com/acme/skills',
            },
          ],
        }),
      );
      return;
    }
    if (request.method === 'GET' && request.url === '/api/v1/skills/audit/acme/skills/weather') {
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(
        JSON.stringify({
          id: 'acme/skills/weather',
          contentHash: currentHash,
          audit: {
            scannerName: 'Cisco AI Skill Scanner',
            scannerVersion: '2.0.12',
            policyName: 'balanced',
            policyVersion: '1.0',
            policyFingerprint: 'b'.repeat(64),
            status: 'pass',
            summary: 'No scanner findings.',
            auditedAt: '2026-07-17T10:00:00Z',
            riskLevel: 'low',
            categories: [],
            score: 100,
            rank: 'S',
            scoreDeductions: [],
          },
        }),
      );
      return;
    }
    if (request.method === 'GET' && request.url?.startsWith('/api/v1/skills/')) {
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(JSON.stringify(payload()));
      return;
    }
    if (request.method === 'POST' && request.url?.startsWith('/api/v1/skills/telemetry/')) {
      const url = new URL(request.url, 'http://localhost');
      assert.equal(url.searchParams.get('client'), 'wardn-cli');
      telemetryRequests += 1;
      response.writeHead(204);
      response.end();
      return;
    }
    response.writeHead(404);
    response.end();
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  apiBaseUrl = `http://127.0.0.1:${address.port}/api/v1`;
});

after(async () => {
  await new Promise((resolve, reject) =>
    server.close((error) => (error ? reject(error) : resolve())),
  );
  await rm(target, { recursive: true, force: true });
});

test('CLI installs, updates, and removes a Wardn-managed skill', async () => {
  const runtime = {
    version: '0.1.0',
    environment: { WARDN_HUB_API_BASE_URL: apiBaseUrl },
  };
  assert.equal(
    await runCli(['install', 'acme/skills/weather', '--target', target, '--json'], runtime),
    0,
  );
  assert.equal(telemetryRequests, 1);
  assert.match(await readFile(join(target, 'weather/SKILL.md'), 'utf8'), /# a/);

  currentHash = 'b'.repeat(64);
  assert.equal(
    await runCli(['update', 'weather', '--target', target, '--json'], runtime),
    0,
  );
  assert.equal(telemetryRequests, 1);
  assert.match(await readFile(join(target, 'weather/SKILL.md'), 'utf8'), /# b/);

  assert.equal(
    await runCli(['remove', 'weather', '--target', target, '--yes', '--json'], runtime),
    0,
  );
  await assert.rejects(() => readFile(join(target, 'weather/SKILL.md')), /ENOENT/);
});

test('CLI exposes the complete script-free resolver workflow', async () => {
  const runtime = {
    version: '0.1.0',
    environment: { WARDN_HUB_API_BASE_URL: apiBaseUrl },
  };
  const output = [];
  const originalLog = console.log;
  console.log = (...values) => output.push(values.join(' '));
  const bundleDirectories = [];
  try {
    assert.equal(await runCli(['search', 'weather', '--json'], runtime), 0);
    assert.equal(JSON.parse(output.pop()).data[0].id, 'acme/skills/weather');

    assert.equal(await runCli(['audit', 'acme/skills/weather', '--json'], runtime), 0);
    const audit = JSON.parse(output.pop());
    assert.equal(audit.audit.status, 'pass');
    assert.equal(audit.audit.score, 100);

    assert.equal(await runCli(['inspect', 'acme/skills/weather', '--json'], runtime), 0);
    assert.equal(JSON.parse(output.pop()).hash, currentHash);

    assert.equal(
      await runCli(
        [
          'fetch-chunk',
          'acme/skills/weather',
          '--hash',
          currentHash,
          '--offset',
          '0',
          '--length',
          '20',
          '--json',
        ],
        runtime,
      ),
      0,
    );
    const chunk = JSON.parse(output.pop());
    assert.equal(chunk.offset, 0);
    assert.equal(chunk.end, 20);

    assert.equal(
      await runCli(
        [
          'fetch-chunk',
          'acme/skills/weather',
          '--offset',
          '0',
          '--length',
          '20',
          '--json',
        ],
        runtime,
      ),
      0,
    );
    const latestChunk = JSON.parse(output.pop());
    assert.equal(latestChunk.hash, currentHash);
    assert.equal(latestChunk.offset, 0);
    assert.equal(latestChunk.end, 20);

    assert.equal(
      await runCli(
        ['fetch-bundle', 'acme/skills/weather', '--hash', currentHash, '--json'],
        runtime,
      ),
      0,
    );
    const manifest = JSON.parse(output.pop());
    bundleDirectories.push(manifest.directory);
    assert.equal(manifest.fileCount, 1);
    assert.match(await readFile(join(manifest.directory, 'SKILL.md'), 'utf8'), /name: weather/);
    assert.equal(telemetryRequests, 2);

    assert.equal(
      await runCli(
        ['fetch-bundle', 'acme/skills/weather', '--no-telemetry', '--json'],
        runtime,
      ),
      0,
    );
    const latestManifest = JSON.parse(output.pop());
    bundleDirectories.push(latestManifest.directory);
    assert.equal(latestManifest.hash, currentHash);
    assert.equal(latestManifest.fileCount, 1);
    assert.match(
      await readFile(join(latestManifest.directory, 'SKILL.md'), 'utf8'),
      /name: weather/,
    );
    assert.equal(telemetryRequests, 2);
  } finally {
    console.log = originalLog;
    for (const bundleDirectory of bundleDirectories) {
      await rm(bundleDirectory, { recursive: true, force: true });
    }
  }
});

test('CLI search is human-readable by default and JSON only when requested', async () => {
  const runtime = {
    version: '0.1.0',
    environment: { WARDN_HUB_API_BASE_URL: apiBaseUrl },
  };
  const output = [];
  const originalLog = console.log;
  console.log = (...values) => output.push(values.join(' '));
  try {
    assert.equal(await runCli(['search', 'weather'], runtime), 0);
    const humanOutput = output.join('\n');
    assert.match(humanOutput, /Found 1 skill for "weather":/);
    assert.match(humanOutput, /1\. Weather/);
    assert.match(humanOutput, /ID: acme\/skills\/weather/);
    assert.match(humanOutput, /community · 3 installs · S 100\/100 \(pass\)/);
    assert.match(humanOutput, /https:\/\/hub\.wardnai\.dev\/skills\/acme\/skills\/weather/);
    assert.throws(() => JSON.parse(humanOutput), SyntaxError);

    output.length = 0;
    assert.equal(await runCli(['search', 'weather', '--json'], runtime), 0);
    const jsonOutput = JSON.parse(output.join('\n'));
    assert.equal(jsonOutput.count, 1);
    assert.equal(jsonOutput.data[0].id, 'acme/skills/weather');
    assert.equal(jsonOutput.data[0].auditStatus, 'pass');
  } finally {
    console.log = originalLog;
  }
});
