import type { Metadata } from "next";

import { SkillsPageView, type SkillsSearchParams } from "../skills-page-view";

export const revalidate = 60;

export const metadata: Metadata = {
  alternates: {
    canonical: "/skills/latest",
  },
  description: "Browse the most recently published agent skills on Wardn Hub.",
  title: "Latest Skills",
};

export default function LatestSkillsPage({
  searchParams,
}: {
  searchParams?: SkillsSearchParams;
}) {
  return (
    <SkillsPageView
      canonicalPath="/skills/latest"
      searchParams={searchParams}
      view="latest"
    />
  );
}
