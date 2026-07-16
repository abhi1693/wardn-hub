import type { Metadata } from "next";

import { SkillsPageView, type SkillsSearchParams } from "../skills-page-view";

export const revalidate = 60;

export const metadata: Metadata = {
  alternates: {
    canonical: "/skills/trending",
  },
  description: "Browse agent skills with the most installs over the past seven days.",
  title: "Trending Skills",
};

export default function TrendingSkillsPage({
  searchParams,
}: {
  searchParams?: SkillsSearchParams;
}) {
  return <SkillsPageView searchParams={searchParams} view="trending" />;
}
