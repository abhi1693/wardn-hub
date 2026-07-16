import type { Metadata } from "next";

import { SkillsPageView, type SkillsSearchParams } from "./skills-page-view";

export const revalidate = 60;
export const metadata: Metadata = {
  alternates: {
    canonical: "/skills",
  },
  description: "Browse reusable agent skills imported into Wardn Hub.",
  title: "Skills",
};

export default function SkillsPage({ searchParams }: { searchParams?: SkillsSearchParams }) {
  return <SkillsPageView searchParams={searchParams} view="all-time" />;
}
