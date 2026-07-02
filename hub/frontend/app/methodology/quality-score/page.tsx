import type { Metadata } from "next";

import { PublicHeader } from "@/components/site-header";
import { QUALITY_SCORE_METHODOLOGY_PATH } from "@/lib/registry-facts-shared";
import { siteConfig } from "@/lib/site";

export const revalidate = 3600;

const title = "Wardn Score Methodology";
const description =
  "How Wardn Hub calculates and explains quality scores for published Model Context Protocol server listings.";

export const metadata: Metadata = {
  alternates: {
    canonical: QUALITY_SCORE_METHODOLOGY_PATH,
  },
  description,
  openGraph: {
    description,
    title: `${title} | ${siteConfig.name}`,
    url: QUALITY_SCORE_METHODOLOGY_PATH,
  },
  title,
  twitter: {
    card: "summary",
    description,
    title: `${title} | ${siteConfig.name}`,
  },
};

export default function QualityScoreMethodologyPage() {
  return (
    <div className="server-detail-page">
      <PublicHeader />
      <main className="server-detail-main">
        <section className="category-page-header">
          <div>
            <p className="category-page-kicker">Methodology</p>
            <h1>Wardn Score Methodology</h1>
            <p>
              Wardn Score is a 0-100 quality signal for published MCP server listings. It summarizes
              available registry, source, package, documentation, maintenance, ownership, and
              security evidence so users can compare servers before reading upstream documentation.
            </p>
          </div>
        </section>

        <section className="category-landing-section" aria-labelledby="score-sources">
          <div className="category-section-header">
            <h2 id="score-sources">Evidence sources</h2>
            <p>
              Scores are based on metadata available to Wardn Hub at review time. A report can come
              from scorer-collected evidence or from a Hub fallback when full scorer evidence is not
              yet available.
            </p>
          </div>
          <div className="category-table-wrap">
            <table className="category-top-table">
              <thead>
                <tr>
                  <th>Area</th>
                  <th>What Wardn checks</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Schema completeness</td>
                  <td>Required server metadata, package targets, remotes, capabilities, and version fields.</td>
                </tr>
                <tr>
                  <td>Documentation</td>
                  <td>Installation steps, configuration notes, examples, supported transports, and troubleshooting.</td>
                </tr>
                <tr>
                  <td>Source review</td>
                  <td>Reachable source repository, reviewable README, package files, lockfiles, and workflow evidence.</td>
                </tr>
                <tr>
                  <td>Target metadata</td>
                  <td>Package registry identifiers, versions, transport commands, remote URLs, and endpoint metadata.</td>
                </tr>
                <tr>
                  <td>Maintenance and security</td>
                  <td>Recent update signals, license metadata, owner verification, secret handling, and security evidence.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section className="category-landing-section" aria-labelledby="score-bands">
          <div className="category-section-header">
            <h2 id="score-bands">Score bands</h2>
            <p>
              Wardn Score is a comparison aid, not a guarantee that a server is safe, official, or
              suitable for production. Always verify upstream source and permissions before use.
            </p>
          </div>
          <div className="category-config-grid">
            <article className="category-config-card">
              <h3>90-100 Strong</h3>
              <p>Listing metadata and evidence are complete enough for high-confidence evaluation.</p>
            </article>
            <article className="category-config-card">
              <h3>70-89 Good</h3>
              <p>Most important metadata is present, with some evidence or documentation gaps remaining.</p>
            </article>
            <article className="category-config-card">
              <h3>40-69 Limited</h3>
              <p>Useful registry metadata exists, but reviewers should expect missing setup or trust evidence.</p>
            </article>
            <article className="category-config-card">
              <h3>0-39 Weak</h3>
              <p>Critical metadata, source, package, documentation, or security evidence is missing.</p>
            </article>
          </div>
        </section>
      </main>
    </div>
  );
}
