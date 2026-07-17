import { Download, FileArchive, FileCode2, FileText, Sparkles } from "lucide-react";
import Link from "next/link";
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
  SkillFilesDisclosure,
  SkillsBreadcrumbs,
} from "../../../skills-ui";
import { SkillDetailTabs, type SkillDetailTab } from "./skill-detail-tabs";

type SkillDetailViewProps = {
  initialTab?: SkillDetailTab;
  owner: string;
  repo: string;
  selectedFilePath: string;
  skillSlug: string;
};

function GithubMark() {
  return (
    <svg aria-hidden="true" fill="currentColor" height="22" viewBox="0 0 24 24" width="22">
      <path d="M12 0c6.63 0 12 5.276 12 11.79-.001 5.067-3.29 9.567-8.175 11.187-.6.118-.825-.25-.825-.56 0-.398.015-1.665.015-3.242 0-1.105-.375-1.813-.81-2.181 2.67-.295 5.475-1.297 5.475-5.822 0-1.297-.465-2.344-1.23-3.169.12-.295.54-1.503-.12-3.125 0 0-1.005-.324-3.3 1.209a11.32 11.32 0 0 0-3-.398c-1.02 0-2.04.133-3 .398-2.295-1.518-3.3-1.209-3.3-1.209-.66 1.622-.24 2.83-.12 3.125-.765.825-1.23 1.887-1.23 3.169 0 4.51 2.79 5.527 5.46 5.822-.345.294-.66.81-.765 1.577-.69.31-2.415.81-3.495-.973-.225-.354-.9-1.223-1.845-1.209-1.005.015-.405.56.015.781.51.28 1.095 1.327 1.23 1.666.24.663 1.02 1.93 4.035 1.385 0 .988.015 1.916.015 2.196 0 .31-.225.664-.825.56C3.303 21.374-.003 16.867 0 11.791 0 5.276 5.37 0 12 0Z" />
    </svg>
  );
}

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
  initialTab,
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
  const summary =
    description ||
    "This source did not publish a separate summary. Review SKILL.md before using the skill.";
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
              <div className="skill-detail-heading">
                <div className="skill-detail-heading-line">
                  <h1 id="skill-detail-title">{title}</h1>
                  {listing?.isOfficial ? <OfficialBadge /> : null}
                  <span className="skill-detail-file-count">
                    <FileText aria-hidden="true" size={14} />
                    {files.length}
                  </span>
                </div>
                <div className="skill-detail-byline">
                  <Link href={skillSourcePath(source)}>{source}</Link>
                  <span aria-hidden="true">·</span>
                  <SkillAuditBadge audit={audit} />
                  {contentHash ? (
                    <>
                      <span aria-hidden="true">·</span>
                      <span title={contentHash}>Snapshot {contentHash.slice(0, 12)}</span>
                    </>
                  ) : null}
                </div>
              </div>
            </div>
            <Link
              aria-label={`Open ${source} on GitHub`}
              className="skill-detail-repository-link"
              href={skill.sourceUrl ?? listing?.sourceUrl ?? `https://github.com/${source}`}
              rel="noreferrer"
              target="_blank"
              title="Open source repository"
            >
              <GithubMark />
            </Link>
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
          </dl>
        </div>
      </section>

      <SkillDetailTabs
        fileCount={files.length}
        files={
          <div className="skill-tab-files-layout">
            <aside className="skill-files-desktop" aria-label="Bundle files">
              <div className="skill-files-index">
                <SkillFiles activePath={selectedFile.path} files={files} skillId={id} />
              </div>
            </aside>
            <div className="skill-files-mobile">
              <SkillFilesDisclosure
                activePath={selectedFile.path}
                files={files}
                skillId={id}
              />
            </div>
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
        initialTab={viewingSkillMd ? (initialTab ?? "overview") : "files"}
        overview={
          <div className="skill-tab-overview-layout">
            <section className="skill-overview-summary" aria-labelledby="skill-summary-heading">
              <h2 id="skill-summary-heading">Summary</h2>
              <p>{summary}</p>
            </section>
            <article className="skill-file-panel skill-overview-document">
              <header className="skill-file-header">
                <FileText aria-hidden="true" size={18} />
                <h2>SKILL.md</h2>
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
        overviewPath={skillDetailPath(id)}
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
