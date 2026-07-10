import { FileArchive, FileCode2, FileText, Sparkles } from "lucide-react";
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
  SkillFiles,
  SkillFilesDisclosure,
  SkillsBreadcrumbs,
  SourceRepositoryLink,
} from "../../../skills-ui";

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
  const [skill, sourceSkills] = await Promise.all([
    getPublicSkill(id, { includeBundle: true }).catch((error) => {
      if (isSkillsNotFoundError(error)) notFound();
      throw error;
    }),
    listPublicSkills({ limit: 100, source }).catch(() => []),
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
              </h1>
            </div>
          </div>
        </div>
      </section>

      <section className="skill-detail-layout" aria-label="Skill file browser">
        <SkillFilesDisclosure activePath={selectedFile.path} files={files} skillId={id} />
        <article className="skill-file-panel">
          {description ? (
            <section className="skill-description-panel" aria-label="Description">
              <p>{description}</p>
            </section>
          ) : null}
          <header className="skill-file-header">
            <SkillFileTypeIcon file={selectedFile} />
            <h2>{selectedFile.path}</h2>
            {selectedFile.executable ? (
              <span className="skill-file-executable">Executable</span>
            ) : null}
          </header>
          <SkillFileContents file={selectedFile} />
        </article>

        <aside className="skill-side-panel">
          <SourceRepositoryLink source={source} sourceUrl={skill.sourceUrl ?? listing?.sourceUrl} />
          <SkillFiles activePath={selectedFile.path} files={files} skillId={id} />
          <RelatedSkills currentId={id} skills={sourceSkills} />
        </aside>
      </section>
    </main>
  );
}
