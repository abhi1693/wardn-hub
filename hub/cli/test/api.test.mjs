import assert from 'node:assert/strict';
import { test } from 'node:test';

import { HubClient, telemetryDisabled } from '../dist/index.js';

function skillMarkdown(name = 'weather') {
  return `---\nname: ${name}\ndescription: Check the weather.\n---\n\n# Weather\n`;
}

function bundlePayload(overrides = {}) {
  return {
    id: 'acme/skills/weather',
    hash: 'a'.repeat(64),
    files: [{ path: 'SKILL.md', contents: skillMarkdown() }],
    ...overrides,
  };
}

test('HubClient validates and decodes a complete bundle', async () => {
  const client = new HubClient({
    version: '0.1.0',
    fetchImplementation: async () =>
      new Response(
        JSON.stringify(
          bundlePayload({
            files: [
              { path: 'SKILL.md', contents: skillMarkdown() },
              {
                path: 'assets/icon.bin',
                contents: Buffer.from([0, 1, 2]).toString('base64'),
                encoding: 'base64',
              },
            ],
          }),
        ),
        { status: 200 },
      ),
  });

  const bundle = await client.fetchBundle('acme/skills/weather', 'a'.repeat(64));

  assert.equal(bundle.id, 'acme/skills/weather');
  assert.equal(bundle.files.length, 2);
  assert.deepEqual(bundle.files[1].contents, Buffer.from([0, 1, 2]));
});

test('HubClient rejects traversal paths and duplicate paths', async () => {
  for (const files of [
    [
      { path: 'SKILL.md', contents: skillMarkdown() },
      { path: '../escape', contents: 'bad' },
    ],
    [
      { path: 'SKILL.md', contents: skillMarkdown() },
      { path: 'SKILL.md', contents: skillMarkdown() },
    ],
    [
      { path: 'SKILL.md', contents: skillMarkdown() },
      { path: 'assets/\u202Etxt.exe', contents: 'bad' },
    ],
    [
      { path: 'SKILL.md', contents: skillMarkdown() },
      { path: 'references/unsafe.txt', contents: 'bad\u0000text' },
    ],
  ]) {
    const client = new HubClient({
      version: '0.1.0',
      fetchImplementation: async () =>
        new Response(JSON.stringify(bundlePayload({ files })), { status: 200 }),
    });
    await assert.rejects(() => client.fetchBundle('acme/skills/weather'));
  }
});

test('HubClient rejects invalid root skill metadata and hash drift', async () => {
  const client = new HubClient({
    version: '0.1.0',
    fetchImplementation: async () =>
      new Response(
        JSON.stringify(
          bundlePayload({ files: [{ path: 'SKILL.md', contents: '# Missing frontmatter' }] }),
        ),
        { status: 200 },
      ),
  });

  await assert.rejects(
    () => client.fetchBundle('acme/skills/weather'),
    /YAML frontmatter/,
  );

  const validClient = new HubClient({
    version: '0.1.0',
    fetchImplementation: async () =>
      new Response(JSON.stringify(bundlePayload()), { status: 200 }),
  });
  await assert.rejects(
    () => validClient.fetchBundle('acme/skills/weather', 'b'.repeat(64)),
    /changed since the expected hash/,
  );
});

test('install telemetry identifies the CLI and remains opt-out', async () => {
  let requestedUrl;
  const client = new HubClient({
    version: '0.1.0',
    fetchImplementation: async (input) => {
      requestedUrl = String(input);
      return new Response(null, { status: 204 });
    },
  });

  await client.recordInstall('acme/skills/weather', 'a'.repeat(64));

  const url = new URL(requestedUrl);
  assert.equal(url.searchParams.get('client'), 'wardn-cli');
  assert.equal(url.searchParams.get('resolver_version'), '0.1.0');
  assert.equal(url.searchParams.get('content_hash'), 'a'.repeat(64));
  assert.equal(telemetryDisabled({ WARDN_HUB_DISABLE_TELEMETRY: '1' }), true);
  assert.equal(telemetryDisabled({ DO_NOT_TRACK: '1' }), true);
  assert.equal(telemetryDisabled({}), false);
});

test('HubClient validates compact skill search results', async () => {
  let requestedUrl;
  const client = new HubClient({
    version: '0.1.0',
    fetchImplementation: async (input) => {
      requestedUrl = String(input);
      return new Response(
        JSON.stringify({
          query: 'code audit',
          searchType: 'semantic',
          count: 1,
          durationMs: 3,
          data: [
            {
              id: 'acme/skills/code-audit',
              slug: 'code-audit',
              source: 'acme/skills',
              name: 'Code Audit',
              description: 'Review source safely.',
              isOfficial: false,
              isDuplicate: null,
              installs: 42,
              url: 'https://hub.wardnai.dev/skills/acme/skills/code-audit',
              sourceUrl: 'https://github.com/acme/skills',
            },
          ],
        }),
        { status: 200 },
      );
    },
  });

  const result = await client.search(' code audit ', 'acme', 8);

  assert.equal(result.count, 1);
  assert.equal(result.data[0].id, 'acme/skills/code-audit');
  const url = new URL(requestedUrl);
  assert.equal(url.pathname, '/api/v1/skills/search');
  assert.equal(url.searchParams.get('q'), 'code audit');
  assert.equal(url.searchParams.get('owner'), 'acme');
  assert.equal(url.searchParams.get('limit'), '8');
});

test('HubClient normalizes current audits and treats 404 as unaudited', async () => {
  const longSummary = `${'x'.repeat(239)}\ntrailing`;
  const client = new HubClient({
    version: '0.1.0',
    fetchImplementation: async () =>
      new Response(
        JSON.stringify({
          id: 'acme/skills/weather',
          contentHash: 'a'.repeat(64),
          audits: [
            {
              provider: 'Wardn Policy',
              slug: 'policy',
              status: 'pass',
              summary: 'Initially accepted.',
              auditedAt: '2026-07-17T10:00:00.1Z',
              riskLevel: 'low',
              categories: [],
            },
            {
              provider: 'Wardn Policy',
              slug: 'policy',
              status: 'fail',
              summary: longSummary,
              auditedAt: '2026-07-17T10:00:00.100000000+00:00',
              riskLevel: 'low',
              categories: ['execution'],
            },
            {
              provider: 'Wardn Review',
              slug: 'review',
              status: 'pass',
              summary: 'Needs attention.',
              auditedAt: '2026-07-17T11:00:00Z',
              riskLevel: 'medium',
              categories: null,
            },
          ],
        }),
        { status: 200 },
      ),
  });

  const result = await client.audit('acme/skills/weather');

  assert.equal(result.hardRejectCount, 1);
  assert.equal(result.warningCount, 1);
  assert.equal(result.failureCount, 1);
  assert.equal(result.latestAudits[0].status, 'fail');
  assert.equal(result.latestAudits[0].summaryTruncated, true);
  assert.equal(result.latestAudits[0].summary.length, 240);
  assert.doesNotMatch(result.latestAudits[0].summary, /[\r\n\t]/);

  const unauditedClient = new HubClient({
    version: '0.1.0',
    fetchImplementation: async () => new Response('{}', { status: 404 }),
  });
  assert.deepEqual(await unauditedClient.audit('acme/skills/weather'), {
    id: 'acme/skills/weather',
    auditStatus: 'unaudited',
  });
});

test('HubClient fetches and counts a validated root skill without its bundle', async () => {
  const markdown = `${skillMarkdown()}Emoji: 🧭\n`;
  const client = new HubClient({
    version: '0.1.0',
    fetchImplementation: async (input) => {
      assert.equal(new URL(String(input)).searchParams.has('include_bundle'), false);
      return new Response(JSON.stringify(bundlePayload({ files: [{ path: 'SKILL.md', contents: markdown }] })), {
        status: 200,
      });
    },
  });

  const root = await client.fetchRoot('acme/skills/weather');

  assert.equal(root.contents, markdown);
  assert.equal(root.characters, [...markdown].length);
});
