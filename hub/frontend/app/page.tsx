import { Server } from "lucide-react";
import type { Metadata } from "next";

import { ServerCard } from "@/components/server-card";
import { PublicHeader } from "@/components/site-header";
import { listPublishedRegistryServers } from "@/lib/public-registry";
import { siteConfig } from "@/lib/site";
import { JsonLdScript, registryIndexJsonLd } from "@/lib/structured-data";

export const revalidate = 3600;

export const metadata: Metadata = {
  alternates: {
    canonical: "/",
  },
  description: siteConfig.description,
  openGraph: {
    description: siteConfig.description,
    title: `${siteConfig.tagline} | ${siteConfig.name}`,
    url: "/",
  },
  title: siteConfig.tagline,
  twitter: {
    card: "summary",
    description: siteConfig.description,
    title: `${siteConfig.tagline} | ${siteConfig.name}`,
  },
};

function EmptyState({ title, detail }: { detail: string; title: string }) {
  return (
    <div className="empty-state">
      <div className="empty-title">{title}</div>
      <div className="empty-detail">{detail}</div>
    </div>
  );
}

export default async function Home() {
  const { error, servers } = await (async () => {
    try {
      return {
        error: "",
        servers: await listPublishedRegistryServers({ limit: 60 }),
      };
    } catch (caught) {
      return {
        error: caught instanceof Error ? caught.message : "Unable to load registry.",
        servers: [],
      };
    }
  })();

  return (
    <main className="site-shell">
      <JsonLdScript data={registryIndexJsonLd(servers)} id="registry-index-json-ld" />
      <PublicHeader />
      <section className="workspace">
        <div className="home-view simple-home">
          {error ? <EmptyState detail={error} title="Registry unavailable" /> : null}
          {!error && servers.length === 0 ? (
            <div className="server-grid">
              <article className="server-card empty-server-card">
                <span className="server-card-head">
                  <span className="server-card-icon">
                    <Server size={22} />
                  </span>
                  <span>
                    <strong>No MCP servers published yet</strong>
                    <small>Registry</small>
                  </span>
                </span>
                <span className="server-card-description">
                  Once community listings are published, this page will show one card per MCP
                  server.
                </span>
              </article>
            </div>
          ) : null}
          {servers.length > 0 ? (
            <div className="server-grid">
              {servers.map((server) => (
                <ServerCard key={server.id} server={server} />
              ))}
            </div>
          ) : null}
        </div>
      </section>
    </main>
  );
}
