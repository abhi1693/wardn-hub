import { BarChart3, CheckCircle2, Mail, Megaphone, ShieldCheck } from "lucide-react";
import type { Metadata } from "next";

import { PublicHeader } from "@/components/site-header";
import { siteConfig } from "@/lib/site";

const contactEmail = "desk.abhimanyu@gmail.com";
const title = "Advertise on Wardn Hub";
const description =
  "Reach developers, founders, and AI teams discovering Model Context Protocol servers on Wardn Hub.";

export const metadata: Metadata = {
  alternates: {
    canonical: "/advertise",
  },
  description,
  openGraph: {
    description,
    title,
    url: "/advertise",
  },
  title,
  twitter: {
    card: "summary",
    description,
    title: `${title} | ${siteConfig.name}`,
  },
};

const placements = [
  {
    detail:
      "High-visibility exposure across the registry discovery paths where developers evaluate MCP servers and adjacent tooling.",
    icon: Megaphone,
    meta: "Placement",
    title: "Strategic placement",
  },
  {
    detail:
      "Direct access to technical decision-makers, architects, and lead developers researching AI server capabilities.",
    icon: BarChart3,
    meta: "Audience",
    title: "High-intent audience",
  },
  {
    detail:
      "Campaigns are reserved for products that genuinely improve the MCP and AI workflow ecosystem.",
    icon: ShieldCheck,
    meta: "Integrity",
    title: "Technical relevance",
  },
];

const benefits = [
  "Brand authority in AI tooling",
  "Verified technical audience",
  "Contextual sponsorship placements",
  "Registry relevance review",
];

const processItems = [
  {
    detail: "Send your product details, target audience, campaign objectives, and ideal timing.",
    title: "Initial inquiry",
  },
  {
    detail: "We evaluate technical fit and alignment with the Wardn Hub developer audience.",
    title: "Relevance review",
  },
  {
    detail: "We agree on placement surfaces, messaging, schedule, and campaign scope.",
    title: "Placement strategy",
  },
  {
    detail: "Approved sponsorships launch with clear labeling and registry-appropriate context.",
    title: "Campaign launch",
  },
];

export default function AdvertisePage() {
  const mailtoHref = `mailto:${contactEmail}?subject=${encodeURIComponent(
    "Wardn Hub advertising inquiry",
  )}`;

  return (
    <main className="site-shell">
      <PublicHeader />
      <section className="workspace">
        <div className="advertise-page">
          <section className="advertise-hero" aria-labelledby="advertise-title">
            <div className="advertise-hero-copy">
              <p className="eyebrow">Advertising & Partnerships</p>
              <h1 id="advertise-title">Enterprise sponsorships for the MCP ecosystem.</h1>
              <p>
                Wardn Hub is a focused architectural hub for Model Context Protocol servers. We
                offer visibility to teams building, deploying, securing, and scaling AI
                infrastructure.
              </p>
            </div>
          </section>

          <section className="advertise-grid" aria-label="Advertising options">
            {placements.map((placement) => {
              const Icon = placement.icon;
              return (
                <article className="advertise-card" key={placement.title}>
                  <span className="advertise-card-top">
                    <span className="advertise-card-icon">
                      <Icon size={20} />
                    </span>
                    <span>{placement.meta}</span>
                  </span>
                  <h2>{placement.title}</h2>
                  <p>{placement.detail}</p>
                </article>
              );
            })}
          </section>

          <section className="advertise-visual" aria-label="Enterprise infrastructure">
            <div className="advertise-visual-racks" aria-hidden="true">
              {Array.from({ length: 18 }, (_, index) => (
                <span key={index} />
              ))}
            </div>
            <div className="advertise-visual-label">
              <span>Architectural visibility for infrastructure teams</span>
            </div>
          </section>

          <section className="advertise-partnership-grid">
            <article className="advertise-process">
              <h2>The path to partnership</h2>
              <div className="advertise-process-list">
                {processItems.map((item, index) => (
                  <section className="advertise-process-item" key={item.title}>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <div>
                      <h3>{item.title}</h3>
                      <p>{item.detail}</p>
                    </div>
                  </section>
                ))}
              </div>
            </article>

            <aside className="advertise-partnership-card">
              <h2>Start partnership inquiry</h2>
              <p>
                Tell us what you are building, who you want to reach, and when you want to launch.
                We will confirm sponsorship fit and available placements.
              </p>
              <ul>
                {benefits.map((item) => (
                  <li key={item}>
                    <CheckCircle2 size={17} />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
              <a className="site-nav-cta" href={mailtoHref}>
                <Mail size={16} />
                Email partnerships
              </a>
            </aside>
          </section>
        </div>
      </section>
    </main>
  );
}
