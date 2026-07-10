import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { skillFilePath, skillFilePathSegments } from "@/lib/public-skills";
import { SkillDetailView } from "../../skill-detail-view";

type SkillFilePageProps = {
  params: Promise<{
    filePath: string[];
    owner: string;
    repo: string;
    skillSlug: string;
  }>;
};

export async function generateMetadata({ params }: SkillFilePageProps): Promise<Metadata> {
  const { filePath: segments, owner, repo, skillSlug } = await params;
  const filePath = skillFilePathSegments(segments);
  const skillId = `${owner}/${repo}/${skillSlug}`;
  const canonical = filePath ? skillFilePath(skillId, filePath) : null;

  return {
    ...(canonical ? { alternates: { canonical } } : {}),
    title: filePath ? `${filePath} · ${skillId}` : skillId,
  };
}

export default async function SkillFilePage({ params }: SkillFilePageProps) {
  const { filePath: segments, owner, repo, skillSlug } = await params;
  const filePath = skillFilePathSegments(segments);
  if (!filePath || filePath === "SKILL.md") notFound();

  return (
    <SkillDetailView
      owner={owner}
      repo={repo}
      selectedFilePath={filePath}
      skillSlug={skillSlug}
    />
  );
}
