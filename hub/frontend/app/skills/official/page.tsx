import type { Metadata } from "next";

import { PublicHeader } from "@/components/site-header";
import { groupSkillsByOwner, listPublicSkills } from "@/lib/public-skills";
import { OfficialCreatorsTable, SkillsBreadcrumbs, SkillsPageHeader } from "../skills-ui";

export const metadata: Metadata = {
  alternates: {
    canonical: "/skills/official",
  },
  description: "Browse official skill creators imported into Wardn Hub.",
  title: "Official skills",
};

export default async function OfficialSkillsPage() {
  const state = await (async () => {
    try {
      const skills = await listPublicSkills({ official: true, limit: 500 });
      return { error: "", skills };
    } catch (caught) {
      return {
        error: caught instanceof Error ? caught.message : "Unable to load official skills.",
        skills: [],
      };
    }
  })();
  const owners = groupSkillsByOwner(state.skills);

  return (
    <main className="site-shell">
      <PublicHeader />
      <section className="skills-page-shell">
        <SkillsBreadcrumbs items={[{ label: "official" }]} />
        <SkillsPageHeader
          description="Official creators and repositories in the Wardn Hub skills registry."
          eyebrow="Official"
          stats={[
            { label: "Creators", value: String(owners.length) },
            { label: "Skills", value: String(state.skills.length) },
          ]}
          title="Official"
        />
        <section className="skills-main-panel" aria-label="Official creators">
          {state.error ? (
            <div className="empty-state">
              <div className="empty-title">Unable to load official skills</div>
              <div className="empty-detail">{state.error}</div>
            </div>
          ) : (
            <OfficialCreatorsTable owners={owners} />
          )}
        </section>
      </section>
    </main>
  );
}
