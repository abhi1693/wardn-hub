#!/usr/bin/env node

import { readFile } from 'node:fs/promises';

import { runCli } from '../dist/cli.js';

const packageJson = JSON.parse(
  await readFile(new URL('../package.json', import.meta.url), 'utf8'),
);

process.exitCode = await runCli(process.argv.slice(2), {
  version: packageJson.version,
});
