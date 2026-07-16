import type { Metadata } from "next";
import { ArrowRight, CheckCircle2, Layers3, Search, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { ServerIcon } from "@/components/server-icon";
import { PublicHeader } from "@/components/site-header";
import type { RegistryCategoryRead, RegistryServerRead } from "@/lib/api/generated/model";
import {
  listPublicCategories,
  listPublishedRegistryServerPage,
  serverDetailPath,
} from "@/lib/public-registry";
import { getRegistryFacts } from "@/lib/registry-facts";
import { formatFactDate } from "@/lib/registry-facts-shared";
import { siteConfig } from "@/lib/site";

export const revalidate = 3600;

const homeDescription =
  "Discover MCP servers and reusable agent skills, with the metadata and review signals needed to choose confidently.";

export const metadata: Metadata = {
  alternates: { canonical: "/" },
  description: homeDescription,
  openGraph: {
    description: homeDescription,
    title: `The open agent ecosystem | ${siteConfig.name}`,
    url: "/",
  },
  title: "The open agent ecosystem",
  twitter: {
    card: "summary_large_image",
    description: homeDescription,
    title: `The open agent ecosystem | ${siteConfig.name}`,
  },
};

function scoreLabel(score: number | null | undefined) {
  return typeof score === "number" ? `Wardn Score ${score}` : "Score pending";
}

function categoryLabel(value: string | undefined) {
  if (!value || value === "Modelcontextprotocol Registry") return "MCP server";
  return value.replace(/\bModelcontextprotocol\b/g, "MCP");
}

function serverIconSource(server: RegistryServerRead) {
  const icon = server.icons?.find(
    (item) =>
      (typeof item.src === "string" && item.src) ||
      (typeof item.url === "string" && item.url),
  );
  if (typeof icon?.src === "string") return icon.src;
  if (typeof icon?.url === "string") return icon.url;
  return "";
}

function FeaturedServerCard({ server }: { server: RegistryServerRead }) {
  const category = categoryLabel(server.categories?.[0]?.name);

  return (
    <Link className="home-server-card" href={serverDetailPath(server.name)}>
      <span className="home-server-card-head">
        <ServerIcon src={serverIconSource(server)} title={server.title || server.name} />
        <span className="home-server-card-title">
          <strong>{server.title || server.name}</strong>
          <small>{category}</small>
        </span>
        <ArrowRight aria-hidden="true" size={17} />
      </span>
      <span className="home-server-card-description">{server.description}</span>
      <span className="home-server-card-meta">
        <span>{server.name}</span>
        <strong>{scoreLabel(server.qualityScore)}</strong>
      </span>
    </Link>
  );
}

function CategoryLink({ category }: { category: RegistryCategoryRead }) {
  return (
    <Link className="home-category-link" href={`/categories/${encodeURIComponent(category.slug)}`}>
      <span>{category.name}</span>
      <ArrowRight aria-hidden="true" size={15} />
    </Link>
  );
}

export default async function Home() {
  const [serverResult, categoryResult, registryFacts] = await Promise.all([
    listPublishedRegistryServerPage({ limit: 6 }).catch(() => ({ nextCursor: "", servers: [] })),
    listPublicCategories().catch(() => []),
    getRegistryFacts(),
  ]);
  const servers = serverResult.servers;
  const categories = categoryResult.slice(0, 12);
  const serverCount = registryFacts.publishedServerCount ?? servers.length;

  return (
    <main className="site-shell">
      <PublicHeader />

      <section className="home-hero" aria-labelledby="home-title">
        <div className="home-hero-inner">
          <p className="home-hero-eyebrow">The open agent ecosystem</p>
          <h1 id="home-title">Find the right building blocks for your agents</h1>
          <p className="home-hero-summary">
            Discover MCP servers and reusable agent skills, with the context to compare them
            before they enter your workflow.
          </p>
          <form action="/mcp-servers" className="home-search" method="get" role="search">
            <Search aria-hidden="true" size={21} />
            <label className="sr-only" htmlFor="home-server-search">
              Search MCP servers
            </label>
            <input
              autoComplete="off"
              id="home-server-search"
              name="q"
              placeholder="Search MCP servers by name or capability"
              type="search"
            />
            <button type="submit">Search</button>
          </form>
          <p className="home-registry-facts">
            <span>{serverCount.toLocaleString("en-US")} MCP servers</span>
            <span>{registryFacts.categoryCount ?? categories.length} categories</span>
            <span>Updated {formatFactDate(registryFacts.lastRegistryUpdate)}</span>
          </p>
        </div>
      </section>

      <div className="home-content">
        <section className="home-pathways" aria-labelledby="home-pathways-title">
          <div className="home-section-heading home-pathways-heading">
            <div>
              <p className="home-section-kicker">Start exploring</p>
              <h2 id="home-pathways-title">Two ways into the ecosystem</h2>
            </div>
          </div>
          <div className="home-pathway-grid">
            <Link className="home-pathway-card" href="/mcp-servers">
              <span className="home-pathway-icon" aria-hidden="true">
                <Layers3 size={22} />
              </span>
              <span>
                <strong>MCP servers</strong>
                <small>Compare packages, remote endpoints, transports, and Wardn Score.</small>
              </span>
              <ArrowRight aria-hidden="true" size={19} />
            </Link>
            <Link className="home-pathway-card" href="/skills">
              <span className="home-pathway-icon" aria-hidden="true">
                <CheckCircle2 size={22} />
              </span>
              <span>
                <strong>Agent skills</strong>
                <small>Find reusable workflows for technical, creative, and operational work.</small>
              </span>
              <ArrowRight aria-hidden="true" size={19} />
            </Link>
          </div>
        </section>

        <section className="home-section" aria-labelledby="home-servers-title">
          <div className="home-section-heading">
            <div>
              <p className="home-section-kicker">MCP server registry</p>
              <h2 id="home-servers-title">Explore the latest listings</h2>
              <p>Review the essentials at a glance, then open a listing for the full record.</p>
            </div>
            <Link className="home-section-link" href="/mcp-servers">
              View all servers <ArrowRight aria-hidden="true" size={16} />
            </Link>
          </div>
          {servers.length > 0 ? (
            <div className="home-server-grid">
              {servers.map((server) => (
                <FeaturedServerCard key={server.id} server={server} />
              ))}
            </div>
          ) : (
            <div className="home-inline-empty">The MCP server registry is temporarily unavailable.</div>
          )}
        </section>

        {categories.length > 0 ? (
          <section className="home-section home-category-section" aria-labelledby="home-categories-title">
            <div className="home-section-heading">
              <div>
                <p className="home-section-kicker">Browse by use case</p>
                <h2 id="home-categories-title">Find a category</h2>
              </div>
              <Link className="home-section-link" href="/categories">
                All categories <ArrowRight aria-hidden="true" size={16} />
              </Link>
            </div>
            <div className="home-category-grid">
              {categories.map((category) => (
                <CategoryLink category={category} key={category.id} />
              ))}
            </div>
          </section>
        ) : null}

        <section className="home-evidence" aria-labelledby="home-evidence-title">
          <div className="home-evidence-copy">
            <span className="home-evidence-icon" aria-hidden="true">
              <ShieldCheck size={24} />
            </span>
            <div>
              <p className="home-section-kicker">Evaluation context</p>
              <h2 id="home-evidence-title">See more than a name and description</h2>
              <p>
                Wardn keeps install targets, transport details, environment variables, namespace
                evidence, and review signals close to every server record.
              </p>
            </div>
          </div>
          <div className="home-evidence-links">
            <Link href="/methodology/quality-score">How Wardn Score works</Link>
            <Link href="/submit">Submit an MCP server</Link>
          </div>
        </section>
      </div>
    </main>
  );
}
