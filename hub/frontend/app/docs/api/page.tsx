import Link from "next/link";
import type { Metadata } from "next";

import { PublicHeader } from "@/components/site-header";
import { absoluteUrl, siteConfig } from "@/lib/site";
import { JsonLdScript } from "@/lib/structured-data";

export const revalidate = 3600;

const title = "Wardn Hub API Documentation";
const description =
  "Developer guide for the Wardn Hub API, including registry discovery, server detail, category, catalog, and submission endpoints.";

const endpointGroups = [
  {
    endpoints: "GET /api/v1/mcp/servers",
    purpose:
      "Browse published MCP server listings and filter registry metadata by search, category, registry, transport, and quality signals.",
    audience: "Discovery and catalog integrations",
  },
  {
    endpoints: "GET /api/v1/mcp/servers/{namespace}/{server}",
    purpose:
      "Read the canonical server detail record, including package targets, remote targets, versions, documentation, categories, and trust metadata.",
    audience: "Server detail and comparison pages",
  },
  {
    endpoints: "GET /api/v1/mcp/categories",
    purpose:
      "List public MCP server categories used for discovery, landing pages, and registry navigation.",
    audience: "Directory navigation",
  },
  {
    endpoints: "GET /api/v1/mcp/catalog",
    purpose:
      "Fetch a public catalog export for sitemap generation, retrieval indexes, and registry synchronization.",
    audience: "Search and retrieval pipelines",
  },
  {
    endpoints: "POST /api/v1/submissions",
    purpose:
      "Create or update authenticated submission drafts before review. Submission routes require an account or API token.",
    audience: "Server publishers",
  },
];

const faqItems = [
  {
    answer:
      "Use the Wardn Hub API to discover and read registry metadata for MCP servers, categories, packages, transports, and trust signals. It is not a runtime API for invoking MCP tools.",
    question: "What is the Wardn Hub API for?",
  },
  {
    answer:
      "Public registry discovery endpoints can be read by crawlers and integrations. Submission and account endpoints require authentication and should be treated as publisher workflows.",
    question: "Do API requests require authentication?",
  },
  {
    answer:
      "The interactive OpenAPI UI remains available at /api/v1/docs, but routes under /api are noindexed. This page is the crawlable developer documentation entry point.",
    question: "Why is this page separate from /api/v1/docs?",
  },
  {
    answer:
      "Wardn Hub lists registry metadata. Verify runtime behavior, permissions, package commands, and environment variables in upstream documentation before installing or running a server.",
    question: "Can I rely on registry metadata for installation?",
  },
];

function apiDocsFaqJsonLd() {
  const url = absoluteUrl("/docs/api");
  return {
    "@context": "https://schema.org",
    "@id": `${url}#faq`,
    "@type": "FAQPage",
    mainEntity: faqItems.map((item) => ({
      "@type": "Question",
      acceptedAnswer: {
        "@type": "Answer",
        text: item.answer,
      },
      name: item.question,
    })),
  };
}

export const metadata: Metadata = {
  alternates: {
    canonical: "/docs/api",
  },
  description,
  openGraph: {
    description,
    title,
    url: "/docs/api",
  },
  title,
  twitter: {
    card: "summary",
    description,
    title: `${title} | ${siteConfig.name}`,
  },
};

export default function ApiDocumentationPage() {
  return (
    <div className="server-detail-page">
      <JsonLdScript data={apiDocsFaqJsonLd()} id="api-docs-faq-jsonld" />
      <PublicHeader />
      <main className="server-detail-main">
        <section className="category-page-header">
          <div>
            <p className="category-page-kicker">Developer docs</p>
            <h1>Wardn Hub API Documentation</h1>
            <p>
              Wardn Hub exposes public registry metadata for MCP server discovery, category pages,
              server detail pages, and catalog exports. The API describes listings and submissions;
              it does not run MCP servers, invoke tools, install packages, or manage runtime
              infrastructure.
            </p>
          </div>
        </section>

        <section className="category-landing-section" aria-labelledby="api-overview">
          <div className="category-section-header">
            <h2 id="api-overview">What the API is for</h2>
            <p>
              Use the API when you need structured Wardn Hub registry data instead of the public
              web UI. The main public use cases are listing published MCP servers, reading canonical
              server detail records, building category pages, generating retrieval indexes, and
              keeping downstream catalogs synchronized.
            </p>
          </div>
          <div className="category-config-grid">
            <article className="category-config-card">
              <h3>Registry discovery</h3>
              <p>
                Query published server listings with metadata such as title, description,
                categories, latest version, registry targets, transports, and Wardn Score when
                available.
              </p>
            </article>
            <article className="category-config-card">
              <h3>Publisher submissions</h3>
              <p>
                Authenticated users can create submission drafts and submit MCP server metadata for
                review before publication in the registry.
              </p>
            </article>
            <article className="category-config-card">
              <h3>Retrieval indexes</h3>
              <p>
                Catalog and category endpoints support search engines, answer engines, and internal
                tools that need canonical URLs and factual registry metadata.
              </p>
            </article>
          </div>
        </section>

        <section className="category-landing-section" aria-labelledby="api-endpoints">
          <div className="category-section-header">
            <h2 id="api-endpoints">Primary endpoint groups</h2>
            <p>
              These endpoint groups are the stable public surfaces developers typically need for
              discovery, cataloging, and publishing workflows.
            </p>
          </div>
          <div className="category-table-wrap">
            <table className="category-top-table">
              <thead>
                <tr>
                  <th>Endpoint</th>
                  <th>Use</th>
                  <th>Best for</th>
                </tr>
              </thead>
              <tbody>
                {endpointGroups.map((group) => (
                  <tr key={group.endpoints}>
                    <td>
                      <span>{group.endpoints}</span>
                    </td>
                    <td>{group.purpose}</td>
                    <td>{group.audience}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="category-landing-section" aria-labelledby="api-indexing">
          <div className="category-section-header">
            <h2 id="api-indexing">Authentication and indexing</h2>
            <p>
              Wardn Hub keeps raw API routes under <code>/api</code> noindexed so crawlers do not
              treat proxy routes, account workflows, or interactive API pages as public editorial
              content. This <code>/docs/api</code> page is the crawlable developer acquisition page
              for API documentation.
            </p>
          </div>
          <div className="category-config-grid">
            <article className="category-config-card">
              <h3>Public documentation</h3>
              <p>
                Link to <code>/docs/api</code> from navigation, footer, sitemaps, and retrieval
                guidance when referencing Wardn Hub developer documentation.
              </p>
            </article>
            <article className="category-config-card">
              <h3>Interactive OpenAPI UI</h3>
              <p>
                The live OpenAPI interface is still available for humans at{" "}
                <Link href="/api/v1/docs" rel="nofollow">
                  /api/v1/docs
                </Link>
                , but it remains outside the indexable content surface.
              </p>
            </article>
            <article className="category-config-card">
              <h3>Source verification</h3>
              <p>
                Wardn Hub lists registry metadata. Verify runtime behavior in upstream docs before
                installing packages, adding environment variables, or connecting a server to an MCP
                client.
              </p>
            </article>
          </div>
        </section>

        <section className="category-landing-section" aria-labelledby="api-faq">
          <div className="category-section-header">
            <h2 id="api-faq">API FAQ</h2>
            <p>
              Common answers for developers and AI retrieval systems evaluating Wardn Hub API
              behavior.
            </p>
          </div>
          <div className="category-faq-grid">
            {faqItems.map((item) => (
              <article className="category-faq-item" key={item.question}>
                <h3>{item.question}</h3>
                <p>{item.answer}</p>
              </article>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}
