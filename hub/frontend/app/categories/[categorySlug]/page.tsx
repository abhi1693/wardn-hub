import type { Metadata } from "next";
import Link from "next/link";

import { ServerCard } from "@/components/server-card";
import { PublicHeader } from "@/components/site-header";
import type { RegistryServerRead } from "@/lib/api/generated/model";
import {
  listPublicCategories,
  listPublishedRegistryServers,
  serverDetailPath,
} from "@/lib/public-registry";
import { siteConfig } from "@/lib/site";
import { categoryDetailJsonLd, JsonLdScript } from "@/lib/structured-data";

export const revalidate = 3600;

const TOP_TABLE_SIZE = 10;

type CategoryDetailPageProps = {
  params: Promise<{ categorySlug?: string }>;
};

function scoreValue(server: RegistryServerRead) {
  return server.qualityScore ?? server.latestVersion?.qualityScore ?? null;
}

function scoreLabel(score: number | null | undefined) {
  return typeof score === "number" ? `${score}/100` : "Pending";
}

function dateLabel(value: string) {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat("en", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

function sortedServers(servers: RegistryServerRead[]) {
  return [...servers].sort((left, right) => {
    const leftScore = scoreValue(left) ?? -1;
    const rightScore = scoreValue(right) ?? -1;
    if (rightScore !== leftScore) return rightScore - leftScore;
    return right.updatedAt.localeCompare(left.updatedAt);
  });
}

function sentenceList(values: string[], emptyLabel: string, limit = 5) {
  if (values.length === 0) return emptyLabel;
  const visible = values.slice(0, limit).join(", ");
  const remaining = values.length - limit;
  return remaining > 0 ? `${visible}, and ${remaining} more` : visible;
}

function categoryExplanation(categoryName: string, description?: string) {
  if (description) {
    return `${description} This page compares published ${categoryName} MCP servers by quality score, update freshness, package metadata, transports, and configuration signals.`;
  }
  return `${categoryName} MCP servers connect AI clients to ${categoryName.toLowerCase()} workflows through the Model Context Protocol. This page compares published servers by quality score, update freshness, package metadata, transports, and configuration signals.`;
}

function CategoryTopServersTable({ servers }: { servers: RegistryServerRead[] }) {
  const topServers = sortedServers(servers).slice(0, TOP_TABLE_SIZE);
  if (topServers.length === 0) return null;

  return (
    <section className="category-landing-section" aria-labelledby="category-top-servers">
      <div className="category-section-header">
        <h2 id="category-top-servers">Top {topServers.length} servers in this category</h2>
        <p>
          This table highlights published servers with the strongest available Wardn metadata for
          quick comparison.
        </p>
      </div>
      <div
        aria-label="Top category servers comparison"
        className="category-table-wrap"
        role="region"
        tabIndex={0}
      >
        <table className="category-top-table">
          <thead>
            <tr>
              <th>Server</th>
              <th>Best for</th>
              <th>Score</th>
              <th>Version</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {topServers.map((server) => (
              <tr key={server.id}>
                <td>
                  <Link href={serverDetailPath(server.name)} prefetch={false}>
                    {server.title || server.name}
                  </Link>
                  <span>{server.name}</span>
                </td>
                <td>{server.description}</td>
                <td>{scoreLabel(scoreValue(server))}</td>
                <td>{server.latestVersion?.version ?? "Unknown"}</td>
                <td>{dateLabel(server.updatedAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CategoryConfigSummary({
  argumentNames,
  categoryName,
  environmentNames,
  transports,
}: {
  argumentNames: string[];
  categoryName: string;
  environmentNames: string[];
  transports: string[];
}) {
  const cards = [
    {
      body:
        transports.length > 0
          ? `${categoryName} entries commonly publish ${sentenceList(transports, "listed")} transport metadata. Confirm the transport supported by your MCP client before installing.`
          : `Published ${categoryName} entries do not expose enough transport detail in the current category sample. Open each server page before installation.`,
      label: "Supported transports",
    },
    {
      body:
        environmentNames.length > 0
          ? `Common environment variables in the sampled server metadata include ${sentenceList(environmentNames, "none", 8)}. Treat these as setup inputs, not secrets to commit.`
          : `The sampled ${categoryName} servers do not list shared environment variables in the public metadata. Check each server page and upstream documentation.`,
      label: "Environment variables",
    },
    {
      body:
        argumentNames.length > 0
          ? `Command arguments found in the sampled package metadata include ${sentenceList(argumentNames, "none", 8)}. Review defaults before launch.`
          : `The sampled package metadata does not list common command arguments. Use the server detail pages to verify launch flags and defaults.`,
      label: "Runtime arguments",
    },
  ];

  return (
    <section className="category-landing-section" aria-labelledby="category-config">
      <div className="category-section-header">
        <h2 id="category-config">Common configuration requirements</h2>
        <p>
          Review transports, environment variables, and runtime arguments before connecting an MCP
          client to a {categoryName} server.
        </p>
      </div>
      <div className="category-config-grid">
        {cards.map((card) => (
          <article className="category-config-card" key={card.label}>
            <h3>{card.label}</h3>
            <p>{card.body}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function CategoryFaq({
  categoryName,
  environmentNames,
  serverCount,
  transports,
}: {
  categoryName: string;
  environmentNames: string[];
  serverCount: number;
  transports: string[];
}) {
  const faqs = [
    {
      answer: `The best ${categoryName} MCP servers are the published entries with strong Wardn scores, recent updates, clear package metadata, and configuration details that match your MCP client.`,
      question: `What are the best ${categoryName} MCP servers?`,
    },
    {
      answer: `Compare the top ${serverCount} published entries by score, version freshness, description fit, transport support, and whether the server documents required environment variables or arguments.`,
      question: `How should I choose a ${categoryName} MCP server?`,
    },
    {
      answer:
        environmentNames.length > 0
          ? `Many entries in this category document environment variables such as ${sentenceList(environmentNames, "none", 6)}. Always verify required secrets on the individual server page.`
          : `Configuration varies by server. Check each detail page for package launch commands, environment variables, and command arguments before installation.`,
      question: `What configuration do ${categoryName} MCP servers usually need?`,
    },
    {
      answer:
        transports.length > 0
          ? `This category includes transport metadata such as ${sentenceList(transports, "none")}. Match the listed transport with the MCP client or host you plan to use.`
          : `Transport metadata is not consistent across the current category sample, so use the server detail page to confirm stdio, HTTP, or remote support.`,
      question: `Which transports are common for ${categoryName} MCP servers?`,
    },
    {
      answer:
        "Wardn Hub lists registry metadata for discovery and comparison. Verify runtime behavior, install commands, permissions, and security requirements in upstream documentation before installing any server.",
      question: `Does Wardn Hub verify runtime behavior for ${categoryName} MCP servers?`,
    },
  ];

  return (
    <section className="category-landing-section" aria-labelledby="category-faq">
      <div className="category-section-header">
        <h2 id="category-faq">FAQ</h2>
      </div>
      <div className="category-faq-grid">
        {faqs.map((faq) => (
          <article className="category-faq-item" key={faq.question}>
            <h3>{faq.question}</h3>
            <p>{faq.answer}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

export async function generateMetadata({ params }: CategoryDetailPageProps): Promise<Metadata> {
  const { categorySlug = "" } = await params;
  const canonical = `/categories/${encodeURIComponent(categorySlug)}`;

  try {
    const categories = await listPublicCategories();
    const category = categories.find((item) => item.slug === categorySlug);
    const categoryName = category?.name ?? categorySlug;
    const title = `Best ${categoryName} MCP Servers`;
    const description =
      category?.description ||
      `Compare the best ${categoryName} MCP servers by package, transport, configuration, and trust signals on Wardn Hub.`;

    return {
      alternates: {
        canonical,
      },
      description,
      openGraph: {
        description,
        title: `${title} | ${siteConfig.name}`,
        url: canonical,
      },
      title,
      twitter: {
        card: "summary",
        description,
        title: `${title} | ${siteConfig.name}`,
      },
    };
  } catch {
    return {
      alternates: {
        canonical,
      },
      description: siteConfig.description,
      title: "Best MCP Servers by Category",
      twitter: {
        card: "summary",
        description: siteConfig.description,
        title: `Best MCP Servers by Category | ${siteConfig.name}`,
      },
    };
  }
}

export default async function CategoryDetailPage({ params }: CategoryDetailPageProps) {
  const { categorySlug = "" } = await params;
  const canonical = `/categories/${encodeURIComponent(categorySlug)}`;
  const { categories, error, servers } = await (async () => {
    try {
      const [categoryResponse, serverResponse] = await Promise.all([
        listPublicCategories(),
        listPublishedRegistryServers({ category: categorySlug, limit: 60 }),
      ]);
      return { categories: categoryResponse, error: "", servers: serverResponse };
    } catch (caught) {
      return {
        categories: [],
        error: caught instanceof Error ? caught.message : "Unable to load category.",
        servers: [],
      };
    }
  })();
  const category = categories.find((item) => item.slug === categorySlug);
  const categoryName = category?.name ?? categorySlug;
  const topServers = sortedServers(servers);
  const transports: string[] = [];
  const environmentNames: string[] = [];
  const argumentNames: string[] = [];
  const explanation = categoryExplanation(categoryName, category?.description);

  return (
    <div className="server-detail-page">
      <JsonLdScript
        data={categoryDetailJsonLd({
          canonicalPath: canonical,
          category,
          categoryName,
          servers,
        })}
        id="category-json-ld"
      />
      <PublicHeader />

      <main className="server-detail-main">
        <section className="category-page-header">
          <div>
            <p className="category-page-kicker">MCP server category</p>
            <h1>Best {categoryName} MCP Servers</h1>
            <p>{explanation}</p>
          </div>
        </section>

        {error ? (
          <div className="empty-state">
            <div className="empty-title">Category unavailable</div>
            <div className="empty-detail">{error}</div>
          </div>
        ) : null}

        {!error && servers.length === 0 ? (
          <div className="empty-state">
            <div className="empty-title">No published servers</div>
            <div className="empty-detail">No published MCP servers are listed in this category.</div>
          </div>
        ) : null}

        {servers.length > 0 ? (
          <>
            <section className="category-landing-summary" aria-label={`${categoryName} summary`}>
              <div>
                <strong>{servers.length}</strong>
                <span>published servers</span>
              </div>
              <div>
                <strong>{transports.length || "Review"}</strong>
                <span>{transports.length === 1 ? "listed transport" : "listed transports"}</span>
              </div>
              <div>
                <strong>{environmentNames.length || "Check"}</strong>
                <span>configuration variables</span>
              </div>
            </section>

            <CategoryTopServersTable servers={topServers} />
            <CategoryConfigSummary
              argumentNames={argumentNames}
              categoryName={categoryName}
              environmentNames={environmentNames}
              transports={transports}
            />
            <CategoryFaq
              categoryName={categoryName}
              environmentNames={environmentNames}
              serverCount={servers.length}
              transports={transports}
            />

            <section className="category-landing-section" aria-labelledby="category-all-servers">
              <div className="category-section-header">
                <h2 id="category-all-servers">All {categoryName} MCP servers</h2>
                <p>Browse every published server currently listed in this category.</p>
              </div>
              <div className="server-grid">
                {servers.map((server) => (
                  <ServerCard key={server.id} server={server} showQualityScore />
                ))}
              </div>
            </section>
          </>
        ) : null}
      </main>
    </div>
  );
}
