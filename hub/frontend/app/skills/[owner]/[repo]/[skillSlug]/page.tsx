import type { Metadata } from "next";
import { FileText, Sparkles } from "lucide-react";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import { PublicHeader } from "@/components/site-header";
import {
  displaySkillName,
  findSkillMd,
  getPublicSkill,
  isSkillsNotFoundError,
  listPublicSkills,
  skillOwnerPath,
  skillSourcePath,
  stripMarkdownFrontmatter,
} from "@/lib/public-skills";
import {
  OfficialBadge,
  RelatedSkills,
  SkillsBreadcrumbs,
  SourceRepositoryLink,
} from "../../../skills-ui";

type SkillDetailPageProps = {
  params: Promise<{
    owner: string;
    repo: string;
    skillSlug: string;
  }>;
};

export async function generateMetadata({ params }: SkillDetailPageProps): Promise<Metadata> {
  const { owner, repo, skillSlug } = await params;
  const id = `${owner}/${repo}/${skillSlug}`;
  return {
    alternates: {
      canonical: `/skills/${[owner, repo, skillSlug].map(encodeURIComponent).join("/")}`,
    },
    title: id,
  };
}

export default async function SkillDetailPage({ params }: SkillDetailPageProps) {
  const { owner, repo, skillSlug } = await params;
  const source = `${owner}/${repo}`;
  const id = `${source}/${skillSlug}`;
  const [skill, sourceSkills] = await Promise.all([
    getPublicSkill(id).catch((error) => {
      if (isSkillsNotFoundError(error)) notFound();
      throw error;
    }),
    listPublicSkills({ limit: 100, source }).catch(() => []),
  ]);
  const listing = sourceSkills.find((item) => item.id === id);
  const skillMd = stripMarkdownFrontmatter(findSkillMd(skill));
  const title = listing ? displaySkillName(listing) : displaySkillName(skill);
  const description = listing?.description?.trim() ?? "";
  const sourceOwnerIconUrl = skill.sourceOwnerIconUrl ?? listing?.sourceOwnerIconUrl;

  return (
    <main className="site-shell">
      <PublicHeader />
      <section className="skill-detail-hero" aria-labelledby="skill-detail-title">
        <div className="skill-detail-hero-inner">
          <SkillsBreadcrumbs
            items={[
              { href: skillOwnerPath(owner), label: owner },
              { href: skillSourcePath(source), label: repo },
              { label: skill.slug },
            ]}
          />
          <div className="skill-detail-title-row">
            <span
              className="skill-detail-icon"
              style={
                sourceOwnerIconUrl
                  ? { backgroundImage: `url(${sourceOwnerIconUrl})` }
                  : undefined
              }
              aria-hidden="true"
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

      <section className="skill-detail-layout" aria-label="Skill files">
        <article className="skill-file-panel">
          {description ? (
            <section className="skill-description-panel" aria-label="Description">
              <p>{description}</p>
            </section>
          ) : null}
          <header className="skill-file-header">
            <FileText size={18} />
            <h2>SKILL.md</h2>
          </header>
          {skillMd ? (
            <div className="skill-file-markdown">
              <ReactMarkdown
                rehypePlugins={[rehypeRaw, rehypeSanitize]}
                remarkPlugins={[remarkGfm]}
              >
                {skillMd}
              </ReactMarkdown>
            </div>
          ) : (
            <div className="skill-file-empty">No SKILL.md contents published.</div>
          )}
        </article>

        <aside className="skill-side-panel">
          <SourceRepositoryLink source={source} sourceUrl={skill.sourceUrl ?? listing?.sourceUrl} />
          <RelatedSkills currentId={id} skills={sourceSkills} />
        </aside>
      </section>
    </main>
  );
}
