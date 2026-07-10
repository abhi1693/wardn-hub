import {
  ChevronDown,
  ExternalLink,
  FileArchive,
  FileCode2,
  FileText,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import type { SkillFileRead, SkillRead } from "@/lib/api/generated/model";
import {
  groupSkillsBySource,
  skillDetailPath,
  skillFilePath,
  skillOwnerPath,
  skillSourcePath,
  type SkillOwnerGroup,
  type SkillSourceGroup,
} from "@/lib/public-skills";

type BreadcrumbItem = {
  href?: string;
  label: string;
};

export function SkillsBreadcrumbs({ items }: { items: BreadcrumbItem[] }) {
  return (
    <nav aria-label="Breadcrumb" className="skills-breadcrumbs">
      <Link href="/skills">skills</Link>
      {items.map((item) => (
        <span key={`${item.href ?? item.label}-${item.label}`}>
          <span aria-hidden="true">/</span>
          {item.href ? <Link href={item.href}>{item.label}</Link> : <span>{item.label}</span>}
        </span>
      ))}
    </nav>
  );
}

export function SkillsPageHeader({
  action,
  description,
  eyebrow,
  stats,
  title,
  titleAccessory,
}: {
  action?: ReactNode;
  description?: string;
  eyebrow?: string;
  stats?: Array<{ label: string; value: string }>;
  title: string;
  titleAccessory?: ReactNode;
}) {
  return (
    <section className="skills-page-header">
      <div className="skills-page-header-copy">
        {eyebrow ? <span className="registry-hero-eyebrow">{eyebrow}</span> : null}
        <h1>
          {title}
          {titleAccessory}
        </h1>
        {description ? <p>{description}</p> : null}
      </div>
      {stats?.length ? (
        <dl className="skills-stat-strip">
          {stats.map((stat) => (
            <div key={stat.label}>
              <dt>{stat.label}</dt>
              <dd>{stat.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {action}
    </section>
  );
}

export function OfficialBadge() {
  return <span className="skills-official-badge">Official</span>;
}

export function SkillLeaderboard({
  emptyLabel = "No skills found",
  skills,
}: {
  emptyLabel?: string;
  skills: SkillRead[];
}) {
  if (!skills.length) {
    return (
      <div className="empty-state">
        <div className="empty-title">{emptyLabel}</div>
      </div>
    );
  }

  return (
    <div className="skills-table-shell">
      <div className="skills-table-header" role="row">
        <span>#</span>
        <span>Skill</span>
        <span>Source</span>
      </div>
      {skills.map((skill, index) => (
        <Link className="skills-table-row" href={skillDetailPath(skill.id)} key={skill.id}>
          <span className="skills-table-rank">{index + 1}</span>
          <span className="skills-table-main">
            <strong>
              {skill.name}
              {skill.isOfficial ? <OfficialBadge /> : null}
            </strong>
            <small>{skill.description || skill.slug}</small>
          </span>
          <span className="skills-table-source">{skill.source}</span>
        </Link>
      ))}
    </div>
  );
}

export function SkillCardGrid({
  emptyLabel = "No skills found",
  skills,
}: {
  emptyLabel?: string;
  skills: SkillRead[];
}) {
  if (!skills.length) {
    return (
      <div className="empty-state">
        <div className="empty-title">{emptyLabel}</div>
      </div>
    );
  }

  return (
    <div className="skill-grid">
      {skills.map((skill) => (
        <Link className="skill-card" href={skillDetailPath(skill.id)} key={skill.id}>
          <span className="skill-card-head">
            <span
              className="skill-card-icon"
              style={
                skill.sourceOwnerIconUrl
                  ? { backgroundImage: `url(${skill.sourceOwnerIconUrl})` }
                  : undefined
              }
              aria-hidden="true"
            >
              {skill.sourceOwnerIconUrl ? null : <Sparkles size={20} />}
            </span>
            <span className="skill-card-title-block">
              <strong>
                {skill.name}
                {skill.isOfficial ? <OfficialBadge /> : null}
              </strong>
            </span>
          </span>
          <span className="skill-card-description">{skill.description || skill.slug}</span>
          <span className="skill-card-footer">
            <span>{skill.sourceOwner || skill.source}</span>
            <span>{skill.slug}</span>
          </span>
        </Link>
      ))}
    </div>
  );
}

export function SkillSourceTable({ groups }: { groups: SkillSourceGroup[] }) {
  if (!groups.length) {
    return (
      <div className="empty-state">
        <div className="empty-title">No sources found</div>
      </div>
    );
  }

  return (
    <div className="skills-source-table">
      <div className="skills-source-table-header">
        <span>Source</span>
        <span>Skills</span>
      </div>
      {groups.map((group) => (
        <Link className="skills-source-row" href={skillSourcePath(group.source)} key={group.source}>
          <span className="skills-source-main">
            <strong>
              {group.source}
              {group.isOfficial ? <OfficialBadge /> : null}
            </strong>
          </span>
          <span className="skills-source-skills">
            {group.skills.slice(0, 3).map((skill) => (
              <span key={skill.id}>{skill.name}</span>
            ))}
          </span>
        </Link>
      ))}
    </div>
  );
}

export function OfficialCreatorsTable({ owners }: { owners: SkillOwnerGroup[] }) {
  if (!owners.length) {
    return (
      <div className="empty-state">
        <div className="empty-title">No official creators found</div>
      </div>
    );
  }

  return (
    <div className="skills-source-table">
      <div className="skills-source-table-header official">
        <span>Creator</span>
        <span>Repos</span>
        <span>Skills</span>
      </div>
      {owners.map((owner) => (
        <Link className="skills-source-row official" href={skillOwnerPath(owner.owner)} key={owner.owner}>
          <span className="skills-source-main">
            <strong>
              {owner.owner}
              {owner.isOfficial ? <OfficialBadge /> : null}
            </strong>
            <small>{owner.sources.length} repositories</small>
          </span>
          <span className="skills-source-skills">
            {owner.sources.slice(0, 3).map((source) => (
              <span key={source.source}>{source.repo}</span>
            ))}
          </span>
          <span className="skills-table-number">{owner.skills.length}</span>
        </Link>
      ))}
    </div>
  );
}

export function RelatedSkills({ currentId, skills }: { currentId: string; skills: SkillRead[] }) {
  const related = skills.filter((skill) => skill.id !== currentId).slice(0, 5);

  if (!related.length) return null;

  return (
    <section className="skills-side-section">
      <h2>Related skills</h2>
      <div className="skills-related-list">
        {related.map((skill) => (
          <Link href={skillDetailPath(skill.id)} key={skill.id}>
            <Sparkles aria-hidden="true" size={16} />
            <span>{skill.name}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}

function SkillFileIcon({ file }: { file: SkillFileRead }) {
  if (file.encoding === "base64") {
    return <FileArchive aria-hidden="true" size={16} />;
  }
  if (/\.(?:md|markdown)$/i.test(file.path)) {
    return <FileText aria-hidden="true" size={16} />;
  }
  return <FileCode2 aria-hidden="true" size={16} />;
}

type SkillFilesProps = {
  activePath: string;
  files: SkillFileRead[];
  skillId: string;
};

function sortedSkillFiles(files: SkillFileRead[]) {
  return [...files].sort((left, right) => {
    if (left.path === "SKILL.md") return -1;
    if (right.path === "SKILL.md") return 1;
    return left.path.localeCompare(right.path);
  });
}

function SkillFileLinks({
  activePath,
  files,
  skillId,
}: SkillFilesProps) {
  return (
    <nav aria-label="Skill files" className="skill-file-list">
      {sortedSkillFiles(files).map((file) => {
        const href = skillFilePath(skillId, file.path);
        if (!href) return null;
        const active = file.path === activePath;
        return (
          <Link
            aria-current={active ? "page" : undefined}
            className={`skill-file-list-item${active ? " active" : ""}`}
            href={href}
            key={file.path}
            title={file.path}
          >
            <SkillFileIcon file={file} />
            <span>{file.path}</span>
          </Link>
        );
      })}
    </nav>
  );
}

export function SkillFiles(props: SkillFilesProps) {
  if (!props.files.length) return null;

  return (
    <section className="skills-side-section skill-files-section">
      <h2>
        Files <span className="skill-file-count">{props.files.length}</span>
      </h2>
      <SkillFileLinks {...props} />
    </section>
  );
}

export function SkillFilesDisclosure(props: SkillFilesProps) {
  if (!props.files.length) return null;

  return (
    <details className="skill-file-disclosure">
      <summary>
        <span>
          Files <span className="skill-file-count">{props.files.length}</span>
        </span>
        <ChevronDown aria-hidden="true" size={16} />
      </summary>
      <SkillFileLinks {...props} />
    </details>
  );
}

export function sourceGroupsForSkills(skills: SkillRead[]) {
  return groupSkillsBySource(skills);
}

export function SourceRepositoryLink({ source, sourceUrl }: { source: string; sourceUrl?: string | null }) {
  return (
    <Link
      className="skill-source-link"
      href={sourceUrl || `https://github.com/${source}`}
      rel="noreferrer"
      target="_blank"
    >
      <ExternalLink size={16} />
      Source repository
    </Link>
  );
}
