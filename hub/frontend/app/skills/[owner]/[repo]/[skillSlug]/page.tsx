import type { Metadata } from "next";
import { SkillDetailView } from "./skill-detail-view";

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
  return (
    <SkillDetailView
      owner={owner}
      repo={repo}
      selectedFilePath="SKILL.md"
      skillSlug={skillSlug}
    />
  );
}
