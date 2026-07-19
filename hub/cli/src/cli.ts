import { createInterface } from 'node:readline/promises';

import {
  agents,
  allSkillsDirectories,
  detectInstalledAgents,
  resolveSkillsDirectories,
  validateAgentNames,
} from './agents.js';
import { HubClient, telemetryDisabled } from './api.js';
import {
  findManagedInstallations,
  installBundle,
  materializeTemporaryBundle,
  removeManagedInstallation,
} from './installation.js';
import type {
  InstallResult,
  InstallScope,
  ManagedInstallation,
  SkillAuditResult,
  SkillSearchResult,
  TemporaryBundleManifest,
} from './types.js';
import { skillSlug, validateHash, validateSkillId } from './validation.js';

interface ParsedOptions {
  agentNames: string[];
  all: boolean;
  global: boolean;
  hash?: string;
  help: boolean;
  json: boolean;
  length?: number;
  limit?: number;
  noTelemetry: boolean;
  offset?: number;
  owner?: string;
  positionals: string[];
  project: boolean;
  target?: string;
  yes: boolean;
}

export interface CliRuntimeOptions {
  version: string;
  cwd?: string;
  environment?: NodeJS.ProcessEnv;
}

function takeOptionValue(args: string[], index: number, option: string): [string, number] {
  const value = args[index + 1];
  if (value === undefined || value.startsWith('-')) {
    throw new Error(`${option} requires a value`);
  }
  return [value, index + 1];
}

function parseCanonicalInteger(value: string, option: string): number {
  if (!/^(?:0|[1-9][0-9]*)$/.test(value)) {
    throw new Error(`${option} requires a canonical non-negative integer`);
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed)) {
    throw new Error(`${option} is too large`);
  }
  return parsed;
}

function parseOptions(args: string[]): ParsedOptions {
  const parsed: ParsedOptions = {
    agentNames: [],
    all: false,
    global: false,
    help: false,
    json: false,
    noTelemetry: false,
    positionals: [],
    project: false,
    yes: false,
  };
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === undefined) continue;
    if (argument === '--') {
      parsed.positionals.push(...args.slice(index + 1));
      break;
    }
    if (argument === '-a' || argument === '--agent') {
      const [value, nextIndex] = takeOptionValue(args, index, argument);
      parsed.agentNames.push(value);
      index = nextIndex;
    } else if (argument.startsWith('--agent=')) {
      parsed.agentNames.push(argument.slice('--agent='.length));
    } else if (argument === '--target') {
      const [value, nextIndex] = takeOptionValue(args, index, argument);
      parsed.target = value;
      index = nextIndex;
    } else if (argument.startsWith('--target=')) {
      parsed.target = argument.slice('--target='.length);
    } else if (argument === '--hash') {
      const [value, nextIndex] = takeOptionValue(args, index, argument);
      parsed.hash = value;
      index = nextIndex;
    } else if (argument.startsWith('--hash=')) {
      parsed.hash = argument.slice('--hash='.length);
    } else if (argument === '--owner') {
      const [value, nextIndex] = takeOptionValue(args, index, argument);
      parsed.owner = value;
      index = nextIndex;
    } else if (argument.startsWith('--owner=')) {
      parsed.owner = argument.slice('--owner='.length);
    } else if (argument === '--limit') {
      const [value, nextIndex] = takeOptionValue(args, index, argument);
      parsed.limit = parseCanonicalInteger(value, argument);
      index = nextIndex;
    } else if (argument.startsWith('--limit=')) {
      parsed.limit = parseCanonicalInteger(argument.slice('--limit='.length), '--limit');
    } else if (argument === '--offset') {
      const [value, nextIndex] = takeOptionValue(args, index, argument);
      parsed.offset = parseCanonicalInteger(value, argument);
      index = nextIndex;
    } else if (argument.startsWith('--offset=')) {
      parsed.offset = parseCanonicalInteger(argument.slice('--offset='.length), '--offset');
    } else if (argument === '--length') {
      const [value, nextIndex] = takeOptionValue(args, index, argument);
      parsed.length = parseCanonicalInteger(value, argument);
      index = nextIndex;
    } else if (argument.startsWith('--length=')) {
      parsed.length = parseCanonicalInteger(argument.slice('--length='.length), '--length');
    } else if (argument === '-g' || argument === '--global') {
      parsed.global = true;
    } else if (argument === '-p' || argument === '--project') {
      parsed.project = true;
    } else if (argument === '-y' || argument === '--yes') {
      parsed.yes = true;
    } else if (argument === '--all') {
      parsed.all = true;
    } else if (argument === '--json') {
      parsed.json = true;
    } else if (argument === '--no-telemetry') {
      parsed.noTelemetry = true;
    } else if (argument === '-h' || argument === '--help') {
      parsed.help = true;
    } else if (argument.startsWith('-')) {
      throw new Error(`unknown option: ${argument}`);
    } else {
      parsed.positionals.push(argument);
    }
  }
  if (parsed.global && parsed.project) {
    throw new Error('--global and --project cannot be used together');
  }
  if (parsed.target !== undefined && parsed.agentNames.length > 0) {
    throw new Error('--target and --agent cannot be used together');
  }
  if (parsed.hash !== undefined) validateHash(parsed.hash, 'expected hash');
  return parsed;
}

function scopeFromOptions(options: ParsedOptions): InstallScope {
  return options.global ? 'global' : 'project';
}

function showHelp(): void {
  console.log(`Wardn Skills CLI

Usage:
  wardn-skills search <query> [owner] [--limit 8]
  wardn-skills audit <skill-id>
  wardn-skills inspect <skill-id>
  wardn-skills fetch <skill-id>
  wardn-skills fetch-chunk <skill-id> [--hash <sha256>] --offset <n> --length <n>
  wardn-skills fetch-bundle <skill-id> [--hash <sha256>]
  wardn-skills install <skill-id> [options]
  wardn-skills update [skill-id-or-slug ...] [options]
  wardn-skills remove <skill-id-or-slug ...> [options]

Commands:
  search, find                Search Wardn Hub
  audit                       Read and normalize current audit decisions
  inspect                     Validate root SKILL.md and print snapshot metadata
  fetch                       Fetch a validated root SKILL.md
  fetch-chunk                 Fetch a root SKILL.md chunk, latest by default
  fetch-bundle                Materialize a complete bundle, latest by default
  install, add, i             Install one skill from Wardn Hub
  update, upgrade             Update managed skills to their latest snapshots
  remove, delete, uninstall   Delete managed skills

Options:
  -a, --agent <agent>         Target an agent; repeat for more than one
  -g, --global                Use the agent's user-level skills directory
  -p, --project               Use the project skills directory (default)
      --target <directory>    Use an explicit absolute skills directory
      --hash <sha256>         Require an exact snapshot; latest when omitted
      --owner <owner>         Restrict a search to one owner
      --limit <count>         Return 1-200 search results (default: 8)
      --offset <characters>   Root content offset for fetch-chunk
      --length <characters>   Root content length for fetch-chunk (1-8000)
  -y, --yes                   Skip remove confirmation
      --all                   Remove every Wardn-managed skill in scope
      --json                  Print machine-readable results
      --no-telemetry          Disable telemetry for this command
  -h, --help                  Show help
  -v, --version               Show the CLI version

Agents:
  ${Object.keys(agents).join(', ')}

Examples:
  npx @wardn-ai/skills search "code audit" --json
  npx @wardn-ai/skills audit owner/repository/skill-slug --json
  npx @wardn-ai/skills fetch-bundle owner/repository/skill-slug --json
  npx @wardn-ai/skills install owner/repository/skill-slug -g -a codex
  npx @wardn-ai/skills update skill-slug -g -a codex
  npx @wardn-ai/skills remove skill-slug -g -a codex -y`);
}

function rejectManagementOptions(options: ParsedOptions, command: string): void {
  if (
    options.agentNames.length > 0 ||
    options.all ||
    options.global ||
    options.project ||
    options.target !== undefined ||
    options.yes
  ) {
    throw new Error(`install-management options are not valid for ${command}`);
  }
}

function rejectResolverOptions(options: ParsedOptions, command: string): void {
  if (
    options.owner !== undefined ||
    options.limit !== undefined ||
    options.offset !== undefined ||
    options.length !== undefined
  ) {
    throw new Error(`resolver options are not valid for ${command}`);
  }
}

function requirePlainResolverCommand(options: ParsedOptions, command: string): void {
  rejectManagementOptions(options, command);
  rejectResolverOptions(options, command);
  if (options.hash !== undefined || options.noTelemetry) {
    throw new Error(`--hash and --no-telemetry are not valid for ${command}`);
  }
}

function printJson(value: unknown): void {
  console.log(
    JSON.stringify(value).replace(/[\u007f-\uffff]/g, (character) =>
      `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`,
    ),
  );
}

function rootMetadata(id: string, hash: string, characters: number): string {
  return `Wardn skill id=${id} hash=${hash} characters=${characters}`;
}

function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return count === 1 ? singular : plural;
}

function printSearchResult(result: SkillSearchResult, json: boolean): void {
  if (json) {
    printJson(result);
    return;
  }
  if (result.count === 0) {
    console.log(`No skills found for "${result.query}".`);
    return;
  }
  console.log(
    `Found ${result.count} ${pluralize(result.count, 'skill')} for "${result.query}":`,
  );
  result.data.forEach((skill, index) => {
    const installs = `${skill.installs} ${pluralize(skill.installs, 'install')}`;
    const audit = result.auditEnabled
      ? skill.auditScore !== null && skill.auditRank
        ? `${skill.auditRank} ${skill.auditScore}/100 (${skill.auditStatus})`
        : 'unaudited'
      : null;
    const labels = [skill.isOfficial ? 'official' : 'community', installs, audit].filter(Boolean);
    console.log(`\n${index + 1}. ${skill.name}`);
    console.log(`   ${skill.description}`);
    console.log(`   ID: ${skill.id}`);
    console.log(`   Source: ${skill.source} · ${labels.join(' · ')}`);
    console.log(`   ${skill.url}`);
  });
}

function printAuditResult(result: SkillAuditResult, json: boolean): void {
  if (json) {
    printJson(result);
    return;
  }
  if ('auditStatus' in result) {
    console.log(`No current audit is available for ${result.id}.`);
    return;
  }
  console.log(`Audit for ${result.id}`);
  console.log(`Content hash: ${result.contentHash}`);
  const audit = result.audit;
  console.log(
    `\n${audit.scannerName}: ${audit.status.toUpperCase()} · ${audit.riskLevel} risk`,
  );
  console.log(`  Security score: ${audit.score}/100 · Rank ${audit.rank}`);
  console.log(`  ${audit.summary}`);
  console.log(`  Audited: ${audit.auditedAt}`);
}

function printBundleManifest(manifest: TemporaryBundleManifest, json: boolean): void {
  if (json) {
    printJson(manifest);
    return;
  }
  console.log(`Materialized ${manifest.id} at ${manifest.directory}`);
  console.log(`Hash: ${manifest.hash}`);
  console.log(`Source entrypoint: ${manifest.sourceEntrypoint}`);
  console.log(
    `${manifest.fileCount} ${pluralize(manifest.fileCount, 'file')} · ${manifest.decodedBytes} decoded bytes`,
  );
  manifest.files.forEach((file) => {
    console.log(`  ${file.path}${file.executable ? ' (executable)' : ''}`);
  });
}

async function searchCommand(client: HubClient, options: ParsedOptions): Promise<void> {
  rejectManagementOptions(options, 'search');
  if (
    options.hash !== undefined ||
    options.noTelemetry ||
    options.offset !== undefined ||
    options.length !== undefined
  ) {
    throw new Error('unsupported option for search');
  }
  if (options.positionals.length < 1 || options.positionals.length > 2) {
    throw new Error('search requires a query and accepts one optional owner');
  }
  if (options.owner !== undefined && options.positionals.length === 2) {
    throw new Error('search owner must be provided either positionally or with --owner');
  }
  const query = options.positionals[0];
  if (query === undefined) throw new Error('search requires a query');
  const owner = options.owner ?? options.positionals[1];
  const result = await client.search(query, owner, options.limit ?? 8);
  printSearchResult(result, options.json);
}

async function auditCommand(client: HubClient, options: ParsedOptions): Promise<void> {
  requirePlainResolverCommand(options, 'audit');
  if (options.positionals.length !== 1) {
    throw new Error('audit requires exactly one Wardn skill ID');
  }
  const id = options.positionals[0];
  if (id === undefined) throw new Error('audit requires a Wardn skill ID');
  printAuditResult(await client.audit(id), options.json);
}

async function inspectCommand(client: HubClient, options: ParsedOptions): Promise<void> {
  requirePlainResolverCommand(options, 'inspect');
  if (options.positionals.length !== 1) {
    throw new Error('inspect requires exactly one Wardn skill ID');
  }
  const id = options.positionals[0];
  if (id === undefined) throw new Error('inspect requires a Wardn skill ID');
  const root = await client.fetchRoot(id);
  if (options.json) {
    printJson({ id: root.id, hash: root.hash, characters: root.characters });
  } else {
    console.log(rootMetadata(root.id, root.hash, root.characters));
  }
}

async function fetchCommand(client: HubClient, options: ParsedOptions): Promise<void> {
  requirePlainResolverCommand(options, 'fetch');
  if (options.positionals.length !== 1) {
    throw new Error('fetch requires exactly one Wardn skill ID');
  }
  const id = options.positionals[0];
  if (id === undefined) throw new Error('fetch requires a Wardn skill ID');
  const root = await client.fetchRoot(id);
  if (options.json) {
    printJson(root);
    return;
  }
  console.log(rootMetadata(root.id, root.hash, root.characters));
  process.stdout.write(root.contents);
  if (!root.contents.endsWith('\n')) process.stdout.write('\n');
}

async function fetchChunkCommand(client: HubClient, options: ParsedOptions): Promise<void> {
  rejectManagementOptions(options, 'fetch-chunk');
  if (options.owner !== undefined || options.limit !== undefined || options.noTelemetry) {
    throw new Error('unsupported option for fetch-chunk');
  }
  if (options.positionals.length !== 1) {
    throw new Error('fetch-chunk requires exactly one Wardn skill ID');
  }
  if (options.offset === undefined || options.length === undefined) {
    throw new Error('fetch-chunk requires --offset and --length');
  }
  if (options.offset > 65_535) throw new Error('chunk offset must not exceed 65535');
  if (options.length < 1 || options.length > 8_000) {
    throw new Error('chunk length must be between 1 and 8000 characters');
  }
  const id = options.positionals[0];
  if (id === undefined) throw new Error('fetch-chunk requires a Wardn skill ID');
  const root = await client.fetchRoot(id);
  if (options.hash !== undefined && root.hash !== options.hash) {
    throw new Error('Wardn skill hash changed since inspection');
  }
  if (options.offset >= root.characters) {
    throw new Error('chunk offset is beyond the Wardn skill content');
  }
  const end = Math.min(options.offset + options.length, root.characters);
  const chunk = {
    id: root.id,
    hash: root.hash,
    offset: options.offset,
    end,
    characters: root.characters,
    content: [...root.contents].slice(options.offset, end).join(''),
  };
  if (options.json) {
    printJson(chunk);
    return;
  }
  console.log(
    `Wardn skill id=${chunk.id} hash=${chunk.hash} characters=${chunk.characters} range=${chunk.offset}-${chunk.end}`,
  );
  process.stdout.write(chunk.content);
  if (!chunk.content.endsWith('\n')) process.stdout.write('\n');
}

async function fetchBundleCommand(
  client: HubClient,
  options: ParsedOptions,
  environment: NodeJS.ProcessEnv,
): Promise<void> {
  rejectManagementOptions(options, 'fetch-bundle');
  if (
    options.owner !== undefined ||
    options.limit !== undefined ||
    options.offset !== undefined ||
    options.length !== undefined
  ) {
    throw new Error('unsupported option for fetch-bundle');
  }
  if (options.positionals.length !== 1) {
    throw new Error('fetch-bundle requires exactly one Wardn skill ID');
  }
  const id = options.positionals[0];
  if (id === undefined) throw new Error('fetch-bundle requires a Wardn skill ID');
  const bundle = await client.fetchBundle(id, options.hash);
  const manifest = await materializeTemporaryBundle(bundle);
  if (!options.noTelemetry && !telemetryDisabled(environment)) {
    await client.recordInstall(bundle.id, bundle.hash);
  }
  printBundleManifest(manifest, options.json);
}

async function selectInstallAgent(explicitAgentNames: string[]): Promise<string[]> {
  if (explicitAgentNames.length > 0) return validateAgentNames(explicitAgentNames);
  const detected = await detectInstalledAgents();
  if (detected.length === 1) return detected;
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    const detail = detected.length > 1 ? `; detected: ${detected.join(', ')}` : '';
    throw new Error(`choose an install target with --agent or --target${detail}`);
  }

  const choices = detected.length > 0 ? detected : Object.keys(agents);
  console.log('Select an agent:');
  choices.forEach((name, index) => {
    const agent = agents[name];
    console.log(`  ${index + 1}. ${agent?.displayName ?? name} (${name})`);
  });
  const prompts = createInterface({ input: process.stdin, output: process.stdout });
  try {
    const answer = (await prompts.question(`Agent [${choices[0]}]: `)).trim();
    if (answer.length === 0) return [choices[0] ?? 'universal'];
    const selectedIndex = Number(answer) - 1;
    const selected = Number.isInteger(selectedIndex) ? choices[selectedIndex] : answer;
    return validateAgentNames([selected ?? answer]);
  } finally {
    prompts.close();
  }
}

async function confirmRemoval(installations: ManagedInstallation[]): Promise<boolean> {
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    throw new Error('remove requires --yes in a non-interactive terminal');
  }
  console.log('Wardn will permanently remove:');
  installations.forEach((installation) => console.log(`  ${installation.directory}`));
  const prompts = createInterface({ input: process.stdin, output: process.stdout });
  try {
    const answer = (await prompts.question('Continue? [y/N] ')).trim().toLowerCase();
    return answer === 'y' || answer === 'yes';
  } finally {
    prompts.close();
  }
}

function assertSelectorsFound(
  installations: ManagedInstallation[],
  selectors: string[],
): void {
  const missing = selectors.filter(
    (selector) =>
      !installations.some(
        (installation) =>
          installation.marker.id === selector ||
          skillSlug(installation.marker.id) === selector,
      ),
  );
  if (missing.length > 0) {
    throw new Error(`Wardn-managed skill not found in the selected scope: ${missing.join(', ')}`);
  }
}

function printInstallResults(results: InstallResult[], json: boolean): void {
  if (json) {
    console.log(JSON.stringify(results.length === 1 ? results[0] : results));
    return;
  }
  results.forEach((result) => {
    console.log(`${result.status} ${result.id} at ${result.directory}`);
  });
}

async function installCommand(
  client: HubClient,
  options: ParsedOptions,
  runtime: Required<Pick<CliRuntimeOptions, 'version'>> & {
    cwd: string;
    environment: NodeJS.ProcessEnv;
  },
): Promise<void> {
  rejectResolverOptions(options, 'install');
  if (options.all) {
    throw new Error('--all is not valid for install');
  }
  if (options.positionals.length !== 1) {
    throw new Error('install requires exactly one Wardn skill ID');
  }
  const id = options.positionals[0];
  if (id === undefined) throw new Error('install requires a Wardn skill ID');
  validateSkillId(id);
  const agentNames =
    options.target === undefined ? await selectInstallAgent(options.agentNames) : [];
  const directories = resolveSkillsDirectories({
    agentNames,
    cwd: runtime.cwd,
    scope: scopeFromOptions(options),
    ...(options.target === undefined ? {} : { target: options.target }),
  });
  const bundle = await client.fetchBundle(id, options.hash);
  const results: InstallResult[] = [];
  for (const directory of directories) {
    results.push(await installBundle(bundle, directory));
  }
  if (
    results.some((result) => result.status === 'installed') &&
    !options.noTelemetry &&
    !telemetryDisabled(runtime.environment)
  ) {
    await client.recordInstall(bundle.id, bundle.hash);
  }
  printInstallResults(results, options.json);
}

async function updateCommand(
  client: HubClient,
  options: ParsedOptions,
  cwd: string,
): Promise<void> {
  rejectResolverOptions(options, 'update');
  if (options.hash !== undefined) {
    throw new Error('--hash is only valid for install');
  }
  const directories = allSkillsDirectories({
    cwd,
    scope: scopeFromOptions(options),
    ...(options.target === undefined ? {} : { target: options.target }),
    ...(options.agentNames.length === 0 ? {} : { agentNames: options.agentNames }),
  });
  const installations = await findManagedInstallations(directories, options.positionals);
  assertSelectorsFound(installations, options.positionals);
  if (installations.length === 0) {
    throw new Error('no Wardn-managed skills found in the selected scope');
  }

  const bundles = new Map<string, Awaited<ReturnType<HubClient['fetchBundle']>>>();
  const results: InstallResult[] = [];
  for (const installation of installations) {
    let bundle = bundles.get(installation.marker.id);
    if (bundle === undefined) {
      bundle = await client.fetchBundle(installation.marker.id);
      bundles.set(installation.marker.id, bundle);
    }
    results.push(await installBundle(bundle, installation.skillsDirectory));
  }
  printInstallResults(results, options.json);
}

async function removeCommand(options: ParsedOptions, cwd: string): Promise<void> {
  rejectResolverOptions(options, 'remove');
  if (options.hash !== undefined) {
    throw new Error('--hash is only valid for install');
  }
  if (options.positionals.length === 0 && !options.all) {
    throw new Error('remove requires one or more skills, or --all');
  }
  const selectors = options.all ? [] : options.positionals;
  const directories = allSkillsDirectories({
    cwd,
    scope: scopeFromOptions(options),
    ...(options.target === undefined ? {} : { target: options.target }),
    ...(options.agentNames.length === 0 ? {} : { agentNames: options.agentNames }),
  });
  const installations = await findManagedInstallations(directories, selectors);
  assertSelectorsFound(installations, selectors);
  if (installations.length === 0) {
    throw new Error('no Wardn-managed skills found in the selected scope');
  }
  if (!options.yes && !(await confirmRemoval(installations))) {
    console.log('Removal cancelled.');
    return;
  }
  for (const installation of installations) {
    await removeManagedInstallation(installation);
  }
  const results = installations.map((installation) => ({
    status: 'removed',
    id: installation.marker.id,
    hash: installation.marker.contentHash,
    directory: installation.directory,
  }));
  if (options.json) {
    console.log(JSON.stringify(results.length === 1 ? results[0] : results));
  } else {
    results.forEach((result) => console.log(`removed ${result.id} from ${result.directory}`));
  }
}

export async function runCli(
  argv: string[],
  runtimeOptions: CliRuntimeOptions,
): Promise<number> {
  const runtime = {
    version: runtimeOptions.version,
    cwd: runtimeOptions.cwd ?? process.cwd(),
    environment: runtimeOptions.environment ?? process.env,
  };
  if (argv.length === 0 || argv[0] === '-h' || argv[0] === '--help') {
    showHelp();
    return 0;
  }
  if (argv[0] === '-v' || argv[0] === '--version') {
    console.log(runtime.version);
    return 0;
  }

  const command = argv[0];
  try {
    const options = parseOptions(argv.slice(1));
    if (options.help) {
      showHelp();
      return 0;
    }
    const client = new HubClient({
      version: runtime.version,
      ...(runtime.environment.WARDN_HUB_API_BASE_URL === undefined
        ? {}
        : { apiBaseUrl: runtime.environment.WARDN_HUB_API_BASE_URL }),
    });
    if (command === 'search' || command === 'find') {
      await searchCommand(client, options);
    } else if (command === 'audit') {
      await auditCommand(client, options);
    } else if (command === 'inspect') {
      await inspectCommand(client, options);
    } else if (command === 'fetch') {
      await fetchCommand(client, options);
    } else if (command === 'fetch-chunk') {
      await fetchChunkCommand(client, options);
    } else if (command === 'fetch-bundle') {
      await fetchBundleCommand(client, options, runtime.environment);
    } else if (command === 'install' || command === 'add' || command === 'i') {
      await installCommand(client, options, runtime);
    } else if (command === 'update' || command === 'upgrade') {
      await updateCommand(client, options, runtime.cwd);
    } else if (
      command === 'remove' ||
      command === 'delete' ||
      command === 'uninstall' ||
      command === 'rm'
    ) {
      await removeCommand(options, runtime.cwd);
    } else {
      throw new Error(`unknown command: ${command}`);
    }
    return 0;
  } catch (error) {
    console.error(`Error: ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  }
}
