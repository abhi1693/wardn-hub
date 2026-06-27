import { ServerCard } from "@/components/server-card";
import { PublicHeader } from "@/components/site-header";
import { listPublicCategories, listPublishedRegistryServers } from "@/lib/public-registry";

export const dynamic = "force-dynamic";

type CategoryDetailPageProps = {
  params: Promise<{ categorySlug?: string }>;
};

export default async function CategoryDetailPage({ params }: CategoryDetailPageProps) {
  const { categorySlug = "" } = await params;
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
