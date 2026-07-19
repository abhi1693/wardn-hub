import type { Metadata } from "next";

import { PublicHeader } from "@/components/site-header";
import { listPublicSkillsPage, skillOwnerPath } from "@/lib/public-skills";
import {
  OfficialBadge,
  SkillLeaderboard,
  SkillsBreadcrumbs,
  SkillsPageHeader,
  SourceRepositoryLink,
} from "../../skills-ui";

type SkillSourcePageProps = {
  params: Promise<{
    owner: string;
    repo: string;
  }>;
};

export async function generateMetadata({ params }: SkillSourcePageProps): Promise<Metadata> {
  const { owner, repo } = await params;
  const source = `${owner}/${repo}`;
  return {
    alternates: {
      canonical: `/skills/${[owner, repo].map(encodeURIComponent).join("/")}`,
    },
    description: `Browse skills imported from ${source}.`,
    title: source,
  };
}

export default async function SkillSourcePage({ params }: SkillSourcePageProps) {
  const { owner, repo } = await params;
  const source = `${owner}/${repo}`;
  const state = await (async () => {
    try {
      const response = await listPublicSkillsPage({ limit: 500, source });
      return { auditEnabled: response.auditEnabled, error: "", skills: response.skills };
    } catch (caught) {
      return {
        auditEnabled: false,
        error: caught instanceof Error ? caught.message : "Unable to load skills.",
        skills: [],
      };
    }
  })();
  const isOfficial = state.skills.some((skill) => skill.isOfficial);
  const sourceUrl = state.skills[0]?.sourceUrl;

  return (
    <main className="site-shell">
      <PublicHeader />
      <section className="skills-page-shell">
        <SkillsBreadcrumbs
          items={[
            { href: skillOwnerPath(owner), label: owner },
            { label: repo },
          ]}
        />
        <SkillsPageHeader
          eyebrow="Source"
          stats={[
            { label: "Skills", value: String(state.skills.length) },
          ]}
          title={source}
          titleAccessory={isOfficial ? <OfficialBadge /> : null}
        />
        <div className="skills-content-grid">
          <section className="skills-main-panel" aria-label="Skills">
            {state.error ? (
              <div className="empty-state">
                <div className="empty-title">Unable to load source</div>
                <div className="empty-detail">{state.error}</div>
              </div>
            ) : (
              <SkillLeaderboard
                auditEnabled={state.auditEnabled}
                emptyLabel={`No imported skills for ${source}`}
                skills={state.skills}
              />
            )}
          </section>
          <aside className="skill-side-panel">
            <SourceRepositoryLink source={source} sourceUrl={sourceUrl} />
          </aside>
        </div>
      </section>
    </main>
  );
}
