import Link from "next/link";

import { siteConfig } from "@/lib/site";

const footerSections = [
  {
    links: [
      { href: "/", label: "Explore" },
      { href: "/categories", label: "Categories" },
      { href: "/users", label: "Users" },
    ],
    title: "Registry",
  },
  {
    links: [
      { href: "/submit", label: "Submit" },
      { href: "/submissions", label: "Submissions" },
      { href: "/account/api-tokens", label: "API tokens" },
    ],
    title: "Contribute",
  },
  {
    links: [
      { href: "/sitemap.xml", label: "Sitemap" },
      { href: "/llms.txt", label: "LLMs.txt" },
      { href: "/robots.txt", label: "Robots.txt" },
    ],
    title: "Crawlers",
  },
];

export function SiteFooter() {
  const year = new Date().getFullYear();

  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <div className="site-footer-brand">
          <strong>{siteConfig.name}</strong>
          <span>{siteConfig.tagline}</span>
          <small>© {year} Wardn AI</small>
        </div>

        <nav aria-label="Footer" className="site-footer-nav">
          {footerSections.map((section) => (
            <section className="site-footer-section" key={section.title}>
              <h2>{section.title}</h2>
              <ul>
                {section.links.map((link) => (
                  <li key={link.href}>
                    <Link href={link.href}>{link.label}</Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </nav>
      </div>
    </footer>
  );
}
