import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { SkillDetailView } from "./skill-detail-view";

type SkillDetailPageProps = {
  params: Promise<{
    owner: string;
    repo: string;
    skillSlug: string;
  }>;
  searchParams: Promise<{
    snapshot?: string | string[];
    tab?: string | string[];
  }>;
};

function detailTab(value: string | string[] | undefined) {
  return value === "files" || value === "install" || value === "security"
    ? value
    : "overview";
}

function snapshotHash(value: string | string[] | undefined) {
  if (value === undefined) return undefined;
  const resolved = Array.isArray(value) ? value[0] : value;
  if (!resolved || !/^[a-f0-9]{64}$/.test(resolved)) notFound();
  return resolved;
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
      snapshotHash={snapshotHash(query.snapshot)}
    />
  );
}
