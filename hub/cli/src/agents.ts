import { access } from 'node:fs/promises';
import { homedir } from 'node:os';
import { isAbsolute, join, resolve } from 'node:path';

import type { AgentConfig, InstallScope } from './types.js';

function configHome(): string {
  return process.env.XDG_CONFIG_HOME?.trim() || join(homedir(), '.config');
}

function codexHome(): string {
  return process.env.CODEX_HOME?.trim() || join(homedir(), '.codex');
}

function claudeHome(): string {
  return process.env.CLAUDE_CONFIG_DIR?.trim() || join(homedir(), '.claude');
}

export const agents: Record<string, AgentConfig> = {
  codex: {
    name: 'codex',
    displayName: 'Codex',
    projectSkillsDirectory: '.agents/skills',
    globalSkillsDirectory: () => join(codexHome(), 'skills'),
    detectionDirectories: () => [codexHome(), '/etc/codex'],
  },
  'claude-code': {
    name: 'claude-code',
    displayName: 'Claude Code',
    projectSkillsDirectory: '.claude/skills',
    globalSkillsDirectory: () => join(claudeHome(), 'skills'),
    detectionDirectories: () => [claudeHome()],
  },
  cursor: {
    name: 'cursor',
    displayName: 'Cursor',
    projectSkillsDirectory: '.agents/skills',
    globalSkillsDirectory: () => join(homedir(), '.cursor/skills'),
    detectionDirectories: () => [join(homedir(), '.cursor')],
  },
  opencode: {
    name: 'opencode',
    displayName: 'OpenCode',
    projectSkillsDirectory: '.agents/skills',
    globalSkillsDirectory: () => join(configHome(), 'opencode/skills'),
    detectionDirectories: () => [join(configHome(), 'opencode')],
  },
  'gemini-cli': {
    name: 'gemini-cli',
    displayName: 'Gemini CLI',
    projectSkillsDirectory: '.agents/skills',
    globalSkillsDirectory: () => join(homedir(), '.gemini/skills'),
    detectionDirectories: () => [join(homedir(), '.gemini')],
  },
  'github-copilot': {
    name: 'github-copilot',
    displayName: 'GitHub Copilot',
    projectSkillsDirectory: '.agents/skills',
    globalSkillsDirectory: () => join(homedir(), '.copilot/skills'),
    detectionDirectories: () => [join(homedir(), '.copilot')],
  },
  universal: {
    name: 'universal',
    displayName: 'Universal Agent Skills',
    projectSkillsDirectory: '.agents/skills',
    globalSkillsDirectory: () => join(configHome(), 'agents/skills'),
    detectionDirectories: () => [],
  },
};

async function pathExists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

export function validateAgentNames(names: string[]): string[] {
  const expanded = names.includes('*') ? Object.keys(agents).filter((name) => name !== 'universal') : names;
  const unique = [...new Set(expanded)];
  const invalid = unique.filter((name) => agents[name] === undefined);
  if (invalid.length > 0) {
    throw new Error(
      `unknown agent${invalid.length === 1 ? '' : 's'}: ${invalid.join(', ')}; valid agents: ${Object.keys(agents).join(', ')}`,
    );
  }
  return unique;
}

export async function detectInstalledAgents(): Promise<string[]> {
  const detected: string[] = [];
  for (const [name, agent] of Object.entries(agents)) {
    if (name === 'universal') continue;
    const results = await Promise.all(agent.detectionDirectories().map(pathExists));
    if (results.some(Boolean)) detected.push(name);
  }
  return detected;
}

export function resolveSkillsDirectories(options: {
  agentNames: string[];
  cwd: string;
  scope: InstallScope;
  target?: string;
}): string[] {
  if (options.target !== undefined) {
    if (!isAbsolute(options.target)) {
      throw new Error('--target must be an absolute agent skills directory');
    }
    return [resolve(options.target)];
  }
  const names = validateAgentNames(options.agentNames);
  const directories = names.map((name) => {
    const agent = agents[name];
    if (agent === undefined) throw new Error(`unknown agent: ${name}`);
    return options.scope === 'global'
      ? resolve(agent.globalSkillsDirectory())
      : resolve(options.cwd, agent.projectSkillsDirectory);
  });
  return [...new Set(directories)];
}

export function allSkillsDirectories(options: {
  cwd: string;
  scope: InstallScope;
  target?: string;
  agentNames?: string[];
}): string[] {
  const agentNames =
    options.agentNames !== undefined && options.agentNames.length > 0
      ? options.agentNames
      : Object.keys(agents);
  return resolveSkillsDirectories({
    agentNames,
    cwd: options.cwd,
    scope: options.scope,
    ...(options.target === undefined ? {} : { target: options.target }),
  });
}
