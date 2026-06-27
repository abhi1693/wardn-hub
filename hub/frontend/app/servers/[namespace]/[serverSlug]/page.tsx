import type { Metadata } from "next";

import { getPublishedRegistryServer } from "@/lib/public-registry";

import { ServerDetailClient } from "./server-detail-client";

export const dynamic = "force-dynamic";

type ServerDetailPageProps = {
  params: Promise<{ namespace?: string; serverSlug?: string }>;
};

function serverNameFromParams(params: { namespace?: string; serverSlug?: string }) {
  const namespace = params.namespace ?? "";
  const serverSlug = params.serverSlug ?? "";
  return namespace && serverSlug ? `${namespace}/${serverSlug}` : "";
}

function serverCanonicalPath(serverName: string) {
  return `/servers/${serverName.split("/").map(encodeURIComponent).join("/")}`;
}

export async function generateMetadata({ params }: ServerDetailPageProps): Promise<Metadata> {
  const serverName = serverNameFromParams(await params);
  const canonical = serverName ? serverCanonicalPath(serverName) : "/servers";

  if (!serverName) {
    return {
      alternates: {
        canonical,
      },
      title: "MCP server",
    };
  }

  try {
    const detail = await getPublishedRegistryServer(serverName);
    const server = detail.server;
    const title = server.title || server.name;
    const description = server.description;

    return {
      alternates: {
        canonical,
      },
      description,
      openGraph: {
        description,
        title,
        url: canonical,
      },
      title,
    };
  } catch {
    return {
      alternates: {
        canonical,
      },
      title: serverName,
    };
  }
}

export default async function ServerDetailPage({ params }: ServerDetailPageProps) {
  const serverName = serverNameFromParams(await params);
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
