import { getPublishedRegistryServer } from "@/lib/public-registry";

import { ServerDetailClient } from "./server-detail-client";

export const dynamic = "force-dynamic";

type ServerDetailPageProps = {
  params: Promise<{ namespace?: string; serverSlug?: string }>;
};

export default async function ServerDetailPage({ params }: ServerDetailPageProps) {
  const { namespace = "", serverSlug = "" } = await params;
  const serverName = namespace && serverSlug ? `${namespace}/${serverSlug}` : "";
  const { initialDetail, initialError } = await (async () => {
    if (!serverName) {
      return { initialDetail: null, initialError: "Server route is incomplete." };
    }
    try {
      return { initialDetail: await getPublishedRegistryServer(serverName), initialError: "" };
    } catch (caught) {
      return {
        initialDetail: null,
        initialError: caught instanceof Error ? caught.message : "Unable to load server.",
      };
    }
  })();

  return (
    <ServerDetailClient
      initialDetail={initialDetail}
      initialError={initialError}
      serverName={serverName}
    />
  );
}
