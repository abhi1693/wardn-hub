import type { Metadata } from "next";
import { SkillDetailView } from "./skill-detail-view";

type SkillDetailPageProps = {
  params: Promise<{
    owner: string;
    repo: string;
    skillSlug: string;
  }>;
  searchParams: Promise<{
    tab?: string | string[];
  }>;
};

function detailTab(value: string | string[] | undefined) {
  return value === "files" || value === "install" || value === "security"
    ? value
    : "overview";
}

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

export default async function SkillDetailPage({ params, searchParams }: SkillDetailPageProps) {
  const [{ owner, repo, skillSlug }, query] = await Promise.all([params, searchParams]);
  return (
    <SkillDetailView
      initialTab={detailTab(query.tab)}
      owner={owner}
      repo={repo}
      selectedFilePath="SKILL.md"
      skillSlug={skillSlug}
    />
  );
}
