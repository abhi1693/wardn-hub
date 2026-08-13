import { PublicHeader } from "@/components/site-header";

export default function SkillDetailLoading() {
  return (
    <main aria-busy="true" className="site-shell skill-detail-route-loading">
      <PublicHeader />
      <section aria-label="Loading skill details" className="skill-detail-loading-hero">
        <div className="skill-detail-loading-inner">
          <div className="skill-loading-line breadcrumbs" />
          <div className="skill-detail-loading-title">
            <div className="skill-loading-block icon" />
            <div>
              <div className="skill-loading-line title" />
              <div className="skill-loading-line metadata" />
            </div>
          </div>
        </div>
      </section>
      <div className="skill-detail-loading-tabs" />
      <section className="skill-detail-loading-body">
        <div className="skill-loading-line heading" />
        <div className="skill-loading-line" />
        <div className="skill-loading-line short" />
        <div className="skill-loading-panel" />
      </section>
    </main>
  );
}
