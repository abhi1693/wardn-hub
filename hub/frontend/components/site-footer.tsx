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
    title: "Discover",
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
];

const socialLinks = [
  {
    href: "https://github.com/abhi1693/wardn-hub",
    icon: "github",
    label: "GitHub repository",
  },
  {
    href: "https://x.com/abhi16_93",
    icon: "x",
    label: "X profile",
  },
] as const;

function isExternalHref(href: string) {
  return /^https?:\/\//i.test(href);
}

function SocialIcon({ name }: { name: "github" | "x" }) {
  if (name === "github") {
    return (
      <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24">
        <path
          d="M12 2C6.48 2 2 6.58 2 12.22c0 4.5 2.86 8.32 6.84 9.67.5.09.68-.22.68-.49v-1.9c-2.78.62-3.37-1.22-3.37-1.22-.45-1.18-1.11-1.49-1.11-1.49-.91-.64.07-.63.07-.63 1 .07 1.53 1.06 1.53 1.06.9 1.56 2.35 1.11 2.92.85.09-.66.35-1.11.64-1.37-2.22-.26-4.56-1.14-4.56-5.07 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.3.1-2.71 0 0 .84-.28 2.75 1.05A9.3 9.3 0 0 1 12 6.88c.85 0 1.7.12 2.5.35 1.9-1.33 2.74-1.05 2.74-1.05.55 1.41.2 2.45.1 2.71.64.72 1.03 1.63 1.03 2.75 0 3.94-2.34 4.81-4.57 5.07.36.32.68.95.68 1.92v2.77c0 .27.18.59.69.49A10.12 10.12 0 0 0 22 12.22C22 6.58 17.52 2 12 2Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24">
      <path
        d="M16.86 3h3.04l-6.64 7.59L21.07 21h-6.12l-4.79-6.27L4.67 21H1.63l7.1-8.11L1.24 3h6.27l4.33 5.73L16.86 3Zm-1.07 16.17h1.68L6.59 4.73H4.78l11.01 14.44Z"
        fill="currentColor"
      />
    </svg>
  );
}

export function SiteFooter() {
  const year = new Date().getFullYear();

  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <div className="site-footer-brand">
          <span className="site-footer-kicker">MCP community</span>
          <strong>{siteConfig.name}</strong>
          <span>{siteConfig.tagline}</span>
          <div className="site-footer-social" aria-label="Social links">
            {socialLinks.map((link) => {
              return (
                <a
                  aria-label={link.label}
                  href={link.href}
                  key={link.href}
                  rel="noreferrer"
                  target="_blank"
                >
                  <SocialIcon name={link.icon} />
                </a>
              );
            })}
          </div>
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
        </div>
      </div>
    </footer>
  );
}
