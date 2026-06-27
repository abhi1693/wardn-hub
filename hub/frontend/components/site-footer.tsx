import Link from "next/link";

import { siteConfig } from "@/lib/site";

const footerSections = [
  {
    links: [
      { href: "/", label: "Explore" },
      { href: "/categories", label: "Categories" },
      { href: "/users", label: "Users" },
      { href: "/partners", label: "Partners" },
    ],
    title: "Registry",
  },
  {
    links: [
      { href: "/submit", label: "Submit" },
      { href: "/submissions", label: "Submissions" },
      { href: "/account/api-tokens", label: "API tokens" },
      { href: "/login", label: "Sign in" },
    ],
    title: "Contribute",
  },
  {
    links: [
      { href: "/sitemap.xml", label: "Sitemap" },
      { href: "/llms.txt", label: "LLMs.txt" },
      { href: "/robots.txt", label: "Robots.txt" },
      { href: "https://github.com/abhi1693/wardn-hub", label: "GitHub" },
      { href: "https://x.com/abhi16_93", label: "X / Twitter" },
    ],
    title: "Source",
  },
];

function isExternalHref(href: string) {
  return /^https?:\/\//i.test(href);
}

export function SiteFooter() {
  const year = new Date().getFullYear();

  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <div className="site-footer-brand">
          <span className="site-footer-kicker">MCP registry</span>
          <strong>{siteConfig.name}</strong>
          <span>{siteConfig.tagline}</span>
        </div>

        <nav aria-label="Footer" className="site-footer-nav">
          {footerSections.map((section) => (
            <section className="site-footer-section" key={section.title}>
              <h2>{section.title}</h2>
              <ul>
                {section.links.map((link) => (
                  <li key={link.href}>
                    {isExternalHref(link.href) ? (
                      <a href={link.href} rel="noreferrer" target="_blank">
                        {link.label}
                      </a>
                    ) : (
                      <Link href={link.href}>{link.label}</Link>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </nav>

        <div className="site-footer-bottom">
          <span>© {year} Wardn AI</span>
          <span>Public registry metadata only</span>
          <span>Canonical catalog: hub.wardnai.dev</span>
        </div>
      </div>
    </footer>
  );
}
