import type { Metadata } from "next";

import { SkillsPageView, type SkillsSearchParams } from "../skills-page-view";

export const revalidate = 60;

export const metadata: Metadata = {
  alternates: {
    canonical: "/skills/oldest",
  },
  description: "Browse the oldest published agent skills on Wardn Hub.",
  title: "Oldest Skills",
};

export default function OldestSkillsPage({
  searchParams,
}: {
  searchParams?: SkillsSearchParams;
}) {
  return (
    <SkillsPageView
      canonicalPath="/skills/oldest"
      searchParams={searchParams}
      view="oldest"
    />
  );
}
