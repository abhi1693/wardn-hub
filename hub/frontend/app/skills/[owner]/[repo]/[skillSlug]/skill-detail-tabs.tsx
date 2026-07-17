"use client";

import {
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  Clipboard,
  Download,
  FileStack,
  FileText,
  FolderTree,
  ShieldCheck,
  Terminal,
  UserRound,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { type KeyboardEvent, type ReactNode, useState } from "react";

import { AgentBrandIcon, type AgentBrandIconName } from "./agent-brand-icon";

export type SkillDetailTab = "files" | "install" | "overview" | "security";
type InstallAudience = "agent" | "human";
type InstallScope = "global" | "project";

type AgentTarget = {
  displayName: string;
  globalDirectory: string;
  icon: AgentBrandIconName;
  pickerLabel?: string;
  projectDirectory: string;
  value: string;
};

const CLI_PACKAGE = "@wardn-ai/skills";

const agentTargets: AgentTarget[] = [
  {
    displayName: "Codex",
    globalDirectory: "~/.codex/skills",
    icon: "codex",
    projectDirectory: ".agents/skills",
    value: "codex",
  },
  {
    displayName: "Claude Code",
    globalDirectory: "~/.claude/skills",
    icon: "claude-code",
    projectDirectory: ".claude/skills",
    value: "claude-code",
  },
  {
    displayName: "Cursor",
    globalDirectory: "~/.cursor/skills",
    icon: "cursor",
    projectDirectory: ".agents/skills",
    value: "cursor",
  },
  {
    displayName: "OpenCode",
    globalDirectory: "~/.config/opencode/skills",
    icon: "opencode",
    projectDirectory: ".agents/skills",
    value: "opencode",
  },
  {
    displayName: "Gemini CLI",
    globalDirectory: "~/.gemini/skills",
    icon: "gemini-cli",
    projectDirectory: ".agents/skills",
    value: "gemini-cli",
  },
  {
    displayName: "GitHub Copilot",
    globalDirectory: "~/.copilot/skills",
    icon: "github-copilot",
    pickerLabel: "Copilot",
    projectDirectory: ".agents/skills",
    value: "github-copilot",
  },
];

function shellQuote(value: string) {
  return `'${value.replaceAll("'", "'\\''")}'`;
}

async function copyText(value: string) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // Fall back for browsers and policies that reject the async Clipboard API.
  }

  const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.readOnly = true;
  textarea.tabIndex = -1;
  textarea.style.position = "fixed";
  textarea.style.inset = "0 auto auto 0";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.append(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, value.length);

  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    textarea.remove();
    activeElement?.focus({ preventScroll: true });
  }
}

function CopyAction({
  className,
  label,
  value,
}: {
  className?: string;
  label: string;
  value: string;
}) {
  const [status, setStatus] = useState<"copied" | "failed" | "idle">("idle");

  async function copy() {
    const copied = await copyText(value);
    setStatus(copied ? "copied" : "failed");
    window.setTimeout(() => setStatus("idle"), 1800);
  }

  const actionLabel = status === "copied" ? "Copied" : status === "failed" ? "Copy failed" : label;

  return (
    <button
      className={`skill-copy-action${className ? ` ${className}` : ""}`}
      onClick={copy}
      type="button"
    >
      {status === "copied" ? (
        <Check aria-hidden="true" size={15} />
      ) : (
        <Clipboard aria-hidden="true" size={15} />
      )}
      <span aria-live="polite">{actionLabel}</span>
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

function AgentInstallation({ skillId }: { skillId: string }) {
  const prompt = [
    `Install the Wardn Hub skill ${skillId} with the first-party ${CLI_PACKAGE} CLI.`,
    "First audit the current snapshot and stop if it has a hard reject:",
    `npx -y ${CLI_PACKAGE} audit ${shellQuote(skillId)} --json`,
    "Then identify the current agent target and install the reviewed snapshot globally:",
    `npx -y ${CLI_PACKAGE} install ${shellQuote(skillId)} --global --agent AGENT_NAME`,
    "Open the installed SKILL.md and follow its instructions. Ask before using credentials, configuring an external service, or taking an irreversible action.",
  ].join("\n\n");

  return (
    <section className="skill-install-mode-panel" aria-labelledby="agent-install-heading">
      <h2 id="agent-install-heading">Send this prompt to your agent to install the skill</h2>
      <details className="skill-install-code-disclosure" open>
        <summary>
          <span>
            <FileText aria-hidden="true" size={16} />
            Agent prompt
          </span>
          <ChevronDown aria-hidden="true" size={15} />
        </summary>
        <pre tabIndex={0}>
          <code>{prompt}</code>
        </pre>
      </details>
      <CopyAction className="skill-copy-primary" label="Copy prompt" value={prompt} />
    </section>
  );
}

function HumanInstallation({
  skillId,
  skillSlug,
}: {
  skillId: string;
  skillSlug: string;
}) {
  const [agentValue, setAgentValue] = useState("codex");
  const [scope, setScope] = useState<InstallScope>("global");
  const selectedAgent =
    agentTargets.find((agent) => agent.value === agentValue) ?? agentTargets[0]!;
  const scopeFlag = scope === "global" ? " --global" : "";
  const agentFlag = ` --agent ${selectedAgent.value}`;
  const installCommand = `npx -y ${CLI_PACKAGE} install ${shellQuote(skillId)}${scopeFlag}${agentFlag}`;
  const updateCommand = `npx -y ${CLI_PACKAGE} update ${shellQuote(skillId)}${scopeFlag}${agentFlag}`;
  const removeCommand = `npx -y ${CLI_PACKAGE} remove ${shellQuote(skillId)}${scopeFlag}${agentFlag} --yes`;
  const directory = `${
    scope === "global" ? selectedAgent.globalDirectory : selectedAgent.projectDirectory
  }/${skillSlug}`;

  return (
    <section className="skill-install-mode-panel" aria-labelledby="human-install-heading">
      <div className="skill-install-agent-picker" aria-label="Agent target">
        {agentTargets.map((agent) => (
          <button
            aria-pressed={agent.value === agentValue}
            key={agent.value}
            onClick={() => setAgentValue(agent.value)}
            type="button"
          >
            <AgentBrandIcon name={agent.icon} />
            {agent.pickerLabel ?? agent.displayName}
          </button>
        ))}
      </div>

      <h2 id="human-install-heading">Install for {selectedAgent.displayName}</h2>

      <ol className="skill-install-instructions">
        <li>
          Run the install command below in your terminal.
        </li>
        <li>
          The skill will be installed in your {selectedAgent.displayName} skills directory.
        </li>
        <li>
          Start a new {selectedAgent.displayName} session and ask it to open the installed SKILL.md.
        </li>
      </ol>

      <div className="skill-install-scope-row">
        <span>Install scope</span>
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
      </div>

      <details className="skill-install-code-disclosure" open>
        <summary>
          <span>
            <FileText aria-hidden="true" size={16} />
            Install command
          </span>
          <ChevronDown aria-hidden="true" size={15} />
        </summary>
        <pre tabIndex={0}>
          <code>{installCommand}</code>
        </pre>
      </details>

      <details className="skill-install-directory-disclosure">
        <summary>
          <span>
            <FolderTree aria-hidden="true" size={15} />
            Directory layout
          </span>
          <ChevronRight aria-hidden="true" size={15} />
        </summary>
        <code>{directory}</code>
      </details>

      <CopyAction
        className="skill-copy-primary"
        label="Copy install command"
        value={installCommand}
      />

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
  skillId,
  skillSlug,
}: {
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
        <AgentInstallation skillId={skillId} />
      ) : (
        <HumanInstallation skillId={skillId} skillSlug={skillSlug} />
      )}
    </div>
  );
}

function SkillOverviewUtilities({ onOpenInstallation }: { onOpenInstallation: () => void }) {
  return (
    <aside className="skill-overview-utilities" aria-label="Skill actions">
      <button className="skill-overview-install-cta" onClick={onOpenInstallation} type="button">
        <Download aria-hidden="true" size={16} />
        Install this skill
      </button>
    </aside>
  );
}

export function SkillDetailTabs({
  fileCount,
  files,
  initialTab,
  overview,
  overviewPath,
  security,
  skillId,
  skillSlug,
}: {
  fileCount: number;
  files: ReactNode;
  initialTab: SkillDetailTab;
  overview: ReactNode;
  overviewPath: string;
  security: ReactNode;
  skillId: string;
  skillSlug: string;
}) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<SkillDetailTab>(initialTab);
  const tabs: Array<{
    icon: ReactNode;
    id: SkillDetailTab;
    label: string;
  }> = [
    { icon: <FileStack aria-hidden="true" size={16} />, id: "overview", label: "Overview" },
    {
      icon: <Download aria-hidden="true" size={16} />,
      id: "install",
      label: "Installation Method",
    },
    {
      icon: <FolderTree aria-hidden="true" size={16} />,
      id: "files",
      label: `Files ${fileCount}`,
    },
    { icon: <ShieldCheck aria-hidden="true" size={16} />, id: "security", label: "Security" },
  ];

  const panel =
    activeTab === "overview" ? (
      <div className="skill-detail-overview-shell">
        <div className="skill-detail-overview-main">{overview}</div>
        <SkillOverviewUtilities onOpenInstallation={() => selectTab("install")} />
      </div>
    ) : activeTab === "install" ? (
      <SkillInstallation skillId={skillId} skillSlug={skillSlug} />
    ) : activeTab === "files" ? (
      files
    ) : (
      security
    );

  function selectTab(tab: SkillDetailTab) {
    setActiveTab(tab);
    const tabPath = tab === "overview" ? overviewPath : `${overviewPath}?tab=${tab}`;
    if (`${window.location.pathname}${window.location.search}` !== tabPath) {
      router.push(tabPath, { scroll: false });
    }
  }

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
    selectTab(nextTab.id);
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
              onClick={() => selectTab(tab.id)}
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
