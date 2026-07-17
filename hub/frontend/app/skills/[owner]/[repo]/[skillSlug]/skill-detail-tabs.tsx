"use client";

import {
  Bot,
  Check,
  Clipboard,
  Download,
  FileStack,
  FolderTree,
  ShieldCheck,
  Terminal,
  UserRound,
} from "lucide-react";
import { type KeyboardEvent, type ReactNode, useState } from "react";

type SkillDetailTab = "files" | "install" | "overview" | "security";
type InstallAudience = "agent" | "human";
type InstallScope = "global" | "project";

type AgentTarget = {
  displayName: string;
  globalDirectory: string;
  projectDirectory: string;
  value: string;
};

const CLI_PACKAGE = "@wardn-ai/skills@0.1.0";

const agentTargets: AgentTarget[] = [
  {
    displayName: "Codex",
    globalDirectory: "~/.codex/skills",
    projectDirectory: ".agents/skills",
    value: "codex",
  },
  {
    displayName: "Claude Code",
    globalDirectory: "~/.claude/skills",
    projectDirectory: ".claude/skills",
    value: "claude-code",
  },
  {
    displayName: "Cursor",
    globalDirectory: "~/.cursor/skills",
    projectDirectory: ".agents/skills",
    value: "cursor",
  },
  {
    displayName: "OpenCode",
    globalDirectory: "~/.config/opencode/skills",
    projectDirectory: ".agents/skills",
    value: "opencode",
  },
  {
    displayName: "Gemini CLI",
    globalDirectory: "~/.gemini/skills",
    projectDirectory: ".agents/skills",
    value: "gemini-cli",
  },
  {
    displayName: "GitHub Copilot",
    globalDirectory: "~/.copilot/skills",
    projectDirectory: ".agents/skills",
    value: "github-copilot",
  },
  {
    displayName: "Universal Agent Skills",
    globalDirectory: "~/.config/agents/skills",
    projectDirectory: ".agents/skills",
    value: "universal",
  },
];

function shellQuote(value: string) {
  return `'${value.replaceAll("'", "'\\''")}'`;
}

function CopyAction({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }

  return (
    <button className="skill-copy-action" onClick={copy} type="button">
      {copied ? <Check aria-hidden="true" size={15} /> : <Clipboard aria-hidden="true" size={15} />}
      <span aria-live="polite">{copied ? "Copied" : label}</span>
    </button>
  );
}

function CommandBlock({ command, label }: { command: string; label: string }) {
  return (
    <div className="skill-install-command">
      <div className="skill-install-command-head">
        <span>
          <Terminal aria-hidden="true" size={14} />
          {label}
        </span>
        <CopyAction label="Copy" value={command} />
      </div>
      <pre tabIndex={0}>
        <code>{command}</code>
      </pre>
    </div>
  );
}

function AgentInstallation({ contentHash, skillId }: { contentHash?: string; skillId: string }) {
  const hashFlag = contentHash ? ` --hash ${shellQuote(contentHash)}` : "";
  const prompt = [
    `Install the Wardn Hub skill ${skillId} with the first-party ${CLI_PACKAGE} CLI.`,
    "First audit the current snapshot and stop if it has a hard reject:",
    `npx -y ${CLI_PACKAGE} audit ${shellQuote(skillId)} --json`,
    "Then identify the current agent target and install the reviewed snapshot globally:",
    `npx -y ${CLI_PACKAGE} install ${shellQuote(skillId)} --global --agent AGENT_NAME${hashFlag}`,
    "Open the installed SKILL.md and follow its instructions. Ask before using credentials, configuring an external service, or taking an irreversible action.",
  ].join("\n\n");

  return (
    <section className="skill-install-mode-panel" aria-labelledby="agent-install-heading">
      <div className="skill-install-intro">
        <span className="skill-install-kicker">
          <Bot aria-hidden="true" size={15} />
          Agent handoff
        </span>
        <h2 id="agent-install-heading">Send one bounded prompt to your agent</h2>
        <p>
          The prompt keeps audit review, snapshot pinning, installation, and the first read of
          SKILL.md in one explicit workflow.
        </p>
      </div>
      <div className="skill-agent-prompt">
        <div className="skill-agent-prompt-head">
          <span>Agent prompt</span>
          <CopyAction label="Copy prompt" value={prompt} />
        </div>
        <pre tabIndex={0}>
          <code>{prompt}</code>
        </pre>
      </div>
      <div className="skill-install-note">
        <ShieldCheck aria-hidden="true" size={17} />
        <p>
          Wardn asks the agent to review the current audit before installing. Audit status is a
          signal, not permission to use credentials or external services.
        </p>
      </div>
    </section>
  );
}

function HumanInstallation({
  contentHash,
  skillId,
  skillSlug,
}: {
  contentHash?: string;
  skillId: string;
  skillSlug: string;
}) {
  const [agentValue, setAgentValue] = useState("codex");
  const [scope, setScope] = useState<InstallScope>("global");
  const selectedAgent =
    agentTargets.find((agent) => agent.value === agentValue) ?? agentTargets[0]!;
  const scopeFlag = scope === "global" ? " --global" : "";
  const agentFlag = ` --agent ${selectedAgent.value}`;
  const hashFlag = contentHash ? ` --hash ${shellQuote(contentHash)}` : "";
  const installCommand = `npx -y ${CLI_PACKAGE} install ${shellQuote(skillId)}${scopeFlag}${agentFlag}${hashFlag}`;
  const updateCommand = `npx -y ${CLI_PACKAGE} update ${shellQuote(skillId)}${scopeFlag}${agentFlag}`;
  const removeCommand = `npx -y ${CLI_PACKAGE} remove ${shellQuote(skillId)}${scopeFlag}${agentFlag} --yes`;
  const directory = `${
    scope === "global" ? selectedAgent.globalDirectory : selectedAgent.projectDirectory
  }/${skillSlug}`;

  return (
    <section className="skill-install-mode-panel" aria-labelledby="human-install-heading">
      <div className="skill-install-intro">
        <span className="skill-install-kicker">
          <UserRound aria-hidden="true" size={15} />
          Terminal workflow
        </span>
        <h2 id="human-install-heading">Install for the agent you actually use</h2>
        <p>Choose a target and scope. The command and expected directory update together.</p>
      </div>

      <div className="skill-install-controls">
        <label>
          <span>Agent target</span>
          <select value={agentValue} onChange={(event) => setAgentValue(event.target.value)}>
            {agentTargets.map((agent) => (
              <option key={agent.value} value={agent.value}>
                {agent.displayName}
              </option>
            ))}
          </select>
        </label>
        <fieldset>
          <legend>Install scope</legend>
          <div className="skill-install-scope-switch">
            <button
              aria-pressed={scope === "global"}
              onClick={() => setScope("global")}
              type="button"
            >
              Global
            </button>
            <button
              aria-pressed={scope === "project"}
              onClick={() => setScope("project")}
              type="button"
            >
              This project
            </button>
          </div>
        </fieldset>
      </div>

      <ol className="skill-install-steps">
        <li>
          <span>1</span>
          <p>Open a terminal in the project where you use {selectedAgent.displayName}.</p>
        </li>
        <li>
          <span>2</span>
          <p>Run the hash-pinned install command below.</p>
        </li>
        <li>
          <span>3</span>
          <p>Start a new agent session, then ask it to open the installed SKILL.md.</p>
        </li>
      </ol>

      <CommandBlock command={installCommand} label={`Install for ${selectedAgent.displayName}`} />

      <div className="skill-install-directory">
        <span>
          <FolderTree aria-hidden="true" size={15} />
          Expected directory
        </span>
        <code>{directory}</code>
      </div>

      <details className="skill-manage-disclosure">
        <summary>Already installed? Update or remove it</summary>
        <div className="skill-manage-commands">
          <CommandBlock command={updateCommand} label="Update to latest snapshot" />
          <CommandBlock command={removeCommand} label="Remove managed skill" />
        </div>
      </details>
    </section>
  );
}

function SkillInstallation({
  contentHash,
  skillId,
  skillSlug,
}: {
  contentHash?: string;
  skillId: string;
  skillSlug: string;
}) {
  const [audience, setAudience] = useState<InstallAudience>("agent");

  return (
    <div className="skill-installation-panel">
      <div className="skill-install-audience" aria-label="Installation audience">
        <button
          aria-pressed={audience === "agent"}
          onClick={() => setAudience("agent")}
          type="button"
        >
          <Bot aria-hidden="true" size={16} />
          I&apos;m an Agent
        </button>
        <button
          aria-pressed={audience === "human"}
          onClick={() => setAudience("human")}
          type="button"
        >
          <UserRound aria-hidden="true" size={16} />
          I&apos;m a Human
        </button>
      </div>
      {audience === "agent" ? (
        <AgentInstallation contentHash={contentHash} skillId={skillId} />
      ) : (
        <HumanInstallation contentHash={contentHash} skillId={skillId} skillSlug={skillSlug} />
      )}
    </div>
  );
}

export function SkillDetailTabs({
  contentHash,
  fileCount,
  files,
  initialTab,
  overview,
  security,
  skillId,
  skillSlug,
}: {
  contentHash?: string;
  fileCount: number;
  files: ReactNode;
  initialTab: SkillDetailTab;
  overview: ReactNode;
  security: ReactNode;
  skillId: string;
  skillSlug: string;
}) {
  const [activeTab, setActiveTab] = useState<SkillDetailTab>(initialTab);
  const tabs: Array<{
    icon: ReactNode;
    id: SkillDetailTab;
    label: string;
  }> = [
    { icon: <FileStack aria-hidden="true" size={16} />, id: "overview", label: "Overview" },
    { icon: <Download aria-hidden="true" size={16} />, id: "install", label: "Installation" },
    {
      icon: <FolderTree aria-hidden="true" size={16} />,
      id: "files",
      label: `Files ${fileCount}`,
    },
    { icon: <ShieldCheck aria-hidden="true" size={16} />, id: "security", label: "Security" },
  ];

  const panel =
    activeTab === "overview" ? (
      overview
    ) : activeTab === "install" ? (
      <SkillInstallation contentHash={contentHash} skillId={skillId} skillSlug={skillSlug} />
    ) : activeTab === "files" ? (
      files
    ) : (
      security
    );

  function moveTab(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabs.length - 1;
    if (nextIndex === null) return;

    event.preventDefault();
    const nextTab = tabs[nextIndex];
    if (!nextTab) return;
    setActiveTab(nextTab.id);
    window.requestAnimationFrame(() => document.getElementById(`skill-tab-${nextTab.id}`)?.focus());
  }

  return (
    <section className="skill-detail-tabs-shell">
      <div className="skill-detail-tab-rail">
        <nav aria-label="Skill details" role="tablist">
          {tabs.map((tab, index) => (
            <button
              aria-controls={`skill-tab-panel-${tab.id}`}
              aria-selected={activeTab === tab.id}
              id={`skill-tab-${tab.id}`}
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              onKeyDown={(event) => moveTab(event, index)}
              role="tab"
              tabIndex={activeTab === tab.id ? 0 : -1}
              type="button"
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </nav>
      </div>
      <div
        aria-labelledby={`skill-tab-${activeTab}`}
        className={`skill-detail-tab-panel skill-detail-tab-${activeTab}`}
        id={`skill-tab-panel-${activeTab}`}
        role="tabpanel"
        tabIndex={0}
      >
        {panel}
      </div>
    </section>
  );
}
