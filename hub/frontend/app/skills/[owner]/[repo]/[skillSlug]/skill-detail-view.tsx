import { Download, FileArchive, FileCode2, Files, FileText, Hash, Sparkles } from "lucide-react";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import { PublicHeader } from "@/components/site-header";
import type { SkillFileRead } from "@/lib/api/generated/model";
import {
  displaySkillName,
  getPublicSkill,
  getPublicSkillAudit,
  isSkillsNotFoundError,
  listPublicSkills,
  publishedSkillFiles,
  skillDetailPath,
  skillOwnerPath,
  skillSourcePath,
  stripMarkdownFrontmatter,
} from "@/lib/public-skills";
import {
  OfficialBadge,
  RelatedSkills,
  SkillAuditBadge,
  SkillAuditPanel,
  SkillFiles,
  SkillsBreadcrumbs,
  SourceRepositoryLink,
} from "../../../skills-ui";
import { SkillDetailTabs } from "./skill-detail-tabs";

type SkillDetailViewProps = {
  owner: string;
  repo: string;
  selectedFilePath: string;
  skillSlug: string;
};

function SkillFileTypeIcon({ file }: { file: SkillFileRead }) {
  if (file.encoding === "base64") return <FileArchive aria-hidden="true" size={18} />;
  if (/\.(?:md|markdown)$/i.test(file.path)) {
    return <FileText aria-hidden="true" size={18} />;
  }
  return <FileCode2 aria-hidden="true" size={18} />;
}

function SkillFileContents({ file }: { file: SkillFileRead }) {
  if (file.encoding === "base64") {
    return (
      <div className="skill-file-binary">
        <FileArchive aria-hidden="true" size={24} />
        <strong>Binary preview unavailable</strong>
        <span>This file is stored as base64 and is not rendered in the browser.</span>
      </div>
    );
  }

  const isMarkdown = /\.(?:md|markdown)$/i.test(file.path);
  const contents =
    file.path === "SKILL.md" ? stripMarkdownFrontmatter(file.contents) : file.contents;

  if (!contents) {
    return (
      <div className="skill-file-empty">
        {file.path === "SKILL.md" ? "No SKILL.md contents published." : "This file is empty."}
      </div>
    );
  }

  if (isMarkdown) {
    return (
      <div className="skill-file-markdown">
        <ReactMarkdown
          components={{
            pre: ({ children }) => <pre tabIndex={0}>{children}</pre>,
          }}
          rehypePlugins={[rehypeRaw, rehypeSanitize]}
          remarkPlugins={[remarkGfm]}
        >
          {contents}
        </ReactMarkdown>
      </div>
    );
  }

  return (
    <div className="skill-file-code">
      <pre aria-label={`${file.path} contents`} tabIndex={0}>
        <code>{contents}</code>
      </pre>
    </div>
  );
}

export async function SkillDetailView({
  owner,
  repo,
  selectedFilePath,
  skillSlug,
}: SkillDetailViewProps) {
  const source = `${owner}/${repo}`;
  const id = `${source}/${skillSlug}`;
  const [skill, sourceSkills, audit] = await Promise.all([
    getPublicSkill(id, { includeBundle: true }).catch((error) => {
      if (isSkillsNotFoundError(error)) notFound();
      throw error;
    }),
    listPublicSkills({ limit: 100, source }).catch(() => []),
    getPublicSkillAudit(id),
  ]);
  const files = publishedSkillFiles(skill);
  const selectedFile =
    files.find((file) => file.path === selectedFilePath) ??
    (selectedFilePath === "SKILL.md"
      ? ({ contents: "", encoding: "utf-8", path: "SKILL.md" } satisfies SkillFileRead)
      : null);
  if (!selectedFile) notFound();

  const listing = sourceSkills.find((item) => item.id === id);
  const title = listing ? displaySkillName(listing) : displaySkillName(skill);
  const description = listing?.description?.trim() ?? "";
  const sourceOwnerIconUrl = skill.sourceOwnerIconUrl ?? listing?.sourceOwnerIconUrl;
  const viewingSkillMd = selectedFile.path === "SKILL.md";
  const contentHash = audit?.contentHash ?? skill.hash ?? undefined;

  return (
    <main className="site-shell">
      <PublicHeader />
      <section className="skill-detail-hero" aria-labelledby="skill-detail-title">
        <div className="skill-detail-hero-inner">
          <SkillsBreadcrumbs
            items={[
              { href: skillOwnerPath(owner), label: owner },
              { href: skillSourcePath(source), label: repo },
              viewingSkillMd
                ? { label: skill.slug }
                : { href: skillDetailPath(id), label: skill.slug },
              ...(viewingSkillMd ? [] : [{ label: selectedFile.path }]),
            ]}
          />
          <div className="skill-detail-hero-main">
            <div className="skill-detail-title-row">
              <span
                aria-hidden="true"
                className="skill-detail-icon"
                style={
                  sourceOwnerIconUrl
                    ? { backgroundImage: `url(${sourceOwnerIconUrl})` }
                    : undefined
                }
              >
                {sourceOwnerIconUrl ? null : <Sparkles size={24} />}
              </span>
              <div>
                <span className="registry-hero-eyebrow">{source}</span>
                <h1 id="skill-detail-title">
                  {title}
                  {listing?.isOfficial ? <OfficialBadge /> : null}
                  <SkillAuditBadge audit={audit} />
                </h1>
              </div>
            </div>
            <SourceRepositoryLink source={source} sourceUrl={skill.sourceUrl ?? listing?.sourceUrl} />
          </div>
          <dl className="skill-detail-facts">
            {listing ? (
              <div>
                <dt>
                  <Download aria-hidden="true" size={14} />
                  Installs
                </dt>
                <dd>{listing.installs.toLocaleString("en-US")}</dd>
              </div>
            ) : null}
            <div>
              <dt>
                <Files aria-hidden="true" size={14} />
                Bundle
              </dt>
              <dd>{files.length} files</dd>
            </div>
            {contentHash ? (
              <div>
                <dt>
                  <Hash aria-hidden="true" size={14} />
                  Snapshot
                </dt>
                <dd title={contentHash}>{contentHash.slice(0, 12)}</dd>
              </div>
            ) : null}
          </dl>
        </div>
      </section>

      <SkillDetailTabs
        contentHash={contentHash}
        fileCount={files.length}
        files={
          <div className="skill-tab-files-layout">
            <section className="skill-files-index" aria-label="Bundle files">
              <SkillFiles activePath={selectedFile.path} files={files} skillId={id} />
            </section>
            <article className="skill-file-panel">
              <header className="skill-file-header">
                <SkillFileTypeIcon file={selectedFile} />
                <h2>{selectedFile.path}</h2>
                {selectedFile.executable ? (
                  <span className="skill-file-executable">Executable</span>
                ) : null}
              </header>
              <SkillFileContents file={selectedFile} />
            </article>
          </div>
        }
        initialTab={viewingSkillMd ? "overview" : "files"}
        overview={
          <div className="skill-tab-overview-layout">
            <section className="skill-overview-summary" aria-labelledby="skill-summary-heading">
              <span className="registry-hero-eyebrow">Summary</span>
              <h2 id="skill-summary-heading">What this skill helps an agent do</h2>
              <p>
                {description ||
                  "This source did not publish a separate summary. Review SKILL.md before using the skill."}
              </p>
            </section>
            <article className="skill-file-panel skill-overview-document">
              <header className="skill-file-header">
                <FileText aria-hidden="true" size={18} />
                <h2>SKILL.md</h2>
                <span className="skill-document-label">Published instructions</span>
              </header>
              <SkillFileContents
                file={
                  files.find((file) => file.path === "SKILL.md") ??
                  ({ contents: "", encoding: "utf-8", path: "SKILL.md" } satisfies SkillFileRead)
                }
              />
            </article>
            <RelatedSkills currentId={id} skills={sourceSkills} />
          </div>
        }
        security={
          <div className="skill-tab-security-layout">
            <div className="skill-security-intro">
              <span className="registry-hero-eyebrow">Snapshot security</span>
              <h2>Audit evidence for this exact bundle</h2>
              <p>
                Provider decisions apply to the content hash shown here. Review warnings and risk
                categories before installation.
              </p>
            </div>
            <SkillAuditPanel audit={audit} />
          </div>
        }
        skillId={id}
        skillSlug={skill.slug}
      />
    </main>
  );
}
