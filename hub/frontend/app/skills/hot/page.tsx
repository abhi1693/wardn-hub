import type { Metadata } from "next";

import { SkillsPageView, type SkillsSearchParams } from "../skills-page-view";

export const revalidate = 60;

export const metadata: Metadata = {
  alternates: {
    canonical: "/skills/hot",
  },
  description: "Browse agent skills with the most installs over the past 24 hours.",
  title: "Hot Skills",
};

export default function HotSkillsPage({ searchParams }: { searchParams?: SkillsSearchParams }) {
  return <SkillsPageView searchParams={searchParams} view="hot" />;
}
