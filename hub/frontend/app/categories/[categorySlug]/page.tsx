import type { Metadata } from "next";

import { ServerCard } from "@/components/server-card";
import { PublicHeader } from "@/components/site-header";
import { listPublicCategories, listPublishedRegistryServers } from "@/lib/public-registry";
import { siteConfig } from "@/lib/site";
import { categoryDetailJsonLd, JsonLdScript } from "@/lib/structured-data";

export const revalidate = 3600;

type CategoryDetailPageProps = {
  params: Promise<{ categorySlug?: string }>;
};

export async function generateStaticParams() {
  try {
    const categories = await listPublicCategories();
    return categories.map((category) => ({ categorySlug: category.slug }));
  } catch (error) {
    console.error("Unable to prebuild category pages from the registry API.", error);
    return [];
  }
}

export async function generateMetadata({ params }: CategoryDetailPageProps): Promise<Metadata> {
  const { categorySlug = "" } = await params;
  const canonical = `/categories/${encodeURIComponent(categorySlug)}`;

  try {
    const categories = await listPublicCategories();
    const category = categories.find((item) => item.slug === categorySlug);
    const categoryName = category?.name ?? categorySlug;
    const title = `${categoryName} MCP servers`;
    const description =
      category?.description ||
      `Browse community-curated MCP servers in the ${categoryName} category on Wardn Hub.`;

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
      title: "MCP server category",
      twitter: {
        card: "summary",
        description: siteConfig.description,
        title: `MCP server category | ${siteConfig.name}`,
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
            <h1>{categoryName}</h1>
            {category?.description ? <p>{category.description}</p> : null}
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
          <div className="server-grid">
            {servers.map((server) => (
              <ServerCard key={server.id} server={server} />
            ))}
          </div>
        ) : null}
      </main>
    </div>
  );
}
