import type { Metadata } from "next";

import { getPublishedRegistryServer } from "@/lib/public-registry";
import { siteConfig } from "@/lib/site";
import { JsonLdScript, serverDetailJsonLd } from "@/lib/structured-data";

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
    const title = "MCP server";
    return {
      alternates: {
        canonical,
      },
      title,
      twitter: {
        card: "summary",
        title: `${title} | ${siteConfig.name}`,
      },
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
      title: serverName,
      twitter: {
        card: "summary",
        title: `${serverName} | ${siteConfig.name}`,
      },
    };
  }
}

export default async function ServerDetailPage({ params }: ServerDetailPageProps) {
  const serverName = serverNameFromParams(await params);
  const canonical = serverName ? serverCanonicalPath(serverName) : "/servers";
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
    <>
      {initialDetail ? (
        <JsonLdScript
          data={serverDetailJsonLd(initialDetail, canonical)}
          id="server-detail-json-ld"
        />
      ) : null}
      <ServerDetailClient
        initialDetail={initialDetail}
        initialError={initialError}
        serverName={serverName}
      />
    </>
  );
}
