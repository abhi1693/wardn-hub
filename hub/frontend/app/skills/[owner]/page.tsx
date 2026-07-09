import type { Metadata } from "next";

import { PublicHeader } from "@/components/site-header";
import { listPublicSkills } from "@/lib/public-skills";
import {
  OfficialBadge,
  SkillSourceTable,
  SkillsBreadcrumbs,
  SkillsPageHeader,
  sourceGroupsForSkills,
} from "../skills-ui";

type SkillOwnerPageProps = {
  params: Promise<{
    owner: string;
  }>;
};

export async function generateMetadata({ params }: SkillOwnerPageProps): Promise<Metadata> {
  const { owner } = await params;
  return {
    alternates: {
      canonical: `/skills/${encodeURIComponent(owner)}`,
    },
    description: `Browse skills imported from ${owner}.`,
    title: owner,
  };
}

export default async function SkillOwnerPage({ params }: SkillOwnerPageProps) {
  const { owner } = await params;
  const state = await (async () => {
    try {
      const skills = await listPublicSkills({ limit: 500, owner });
      return { error: "", skills };
    } catch (caught) {
      return {
        error: caught instanceof Error ? caught.message : "Unable to load creator.",
        skills: [],
      };
    }
  })();
  const groups = sourceGroupsForSkills(state.skills);
  const isOfficial = state.skills.some((skill) => skill.isOfficial);

  return (
    <main className="site-shell">
      <PublicHeader />
      <section className="skills-page-shell">
        <SkillsBreadcrumbs items={[{ label: owner }]} />
        <SkillsPageHeader
          eyebrow="Creator"
          stats={[
            { label: "Sources", value: String(groups.length) },
            { label: "Skills", value: String(state.skills.length) },
          ]}
          title={owner}
          titleAccessory={isOfficial ? <OfficialBadge /> : null}
        />
        <section className="skills-main-panel" aria-label="Sources">
          {state.error ? (
            <div className="empty-state">
              <div className="empty-title">Unable to load creator</div>
              <div className="empty-detail">{state.error}</div>
            </div>
          ) : groups.length ? (
            <SkillSourceTable groups={groups} />
          ) : (
            <div className="empty-state">
              <div className="empty-title">No imported skills for {owner}</div>
            </div>
          )}
        </section>
      </section>
    </main>
  );
}
