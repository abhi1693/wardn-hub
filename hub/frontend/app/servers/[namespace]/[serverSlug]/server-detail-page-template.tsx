import type { Metadata } from "next";
import { notFound } from "next/navigation";

import {
  getPublishedRegistryServerSummary,
  getPublishedRegistryServerTab,
  listPublishedRegistryServers,
} from "@/lib/public-registry";
import type { DetailTab } from "@/lib/server-detail-tabs";
import { siteConfig } from "@/lib/site";
import { JsonLdScript, serverDetailJsonLd } from "@/lib/structured-data";

import { ServerDetailClient } from "./server-detail-client";

type ServerDetailParams = {
  namespace?: string;
  serverSlug?: string;
  tab?: string;
};

type ServerDetailTemplateProps = {
  fixedTab?: DetailTab;
  params: Promise<ServerDetailParams>;
};

const routeTabs = new Set<DetailTab>(["schema", "score"]);

export async function generateServerDetailStaticParams(tabs: DetailTab[]) {
  try {
    const servers = await listPublishedRegistryServers();
    return servers.flatMap((server) => {
      const [namespace, serverSlug] = server.name.split("/");
      if (!namespace || !serverSlug) return [];
      return tabs.map((tab) =>
        tab === "overview" ? { namespace, serverSlug } : { namespace, serverSlug, tab },
      );
    });
  } catch (error) {
    console.error("Unable to prebuild server detail pages from the registry API.", error);
    return [];
  }
}

export function generateServerDetailOverviewStaticParams() {
  return generateServerDetailStaticParams(["overview"]);
}

export function generateServerDetailTabStaticParams() {
  return generateServerDetailStaticParams(["schema", "score"]);
}

function serverNameFromParams(params: ServerDetailParams) {
  const namespace = params.namespace ?? "";
  const serverSlug = params.serverSlug ?? "";
  return namespace && serverSlug ? `${namespace}/${serverSlug}` : "";
}

function tabFromParams(params: ServerDetailParams, fixedTab?: DetailTab) {
  if (fixedTab) return fixedTab;
  return routeTabs.has(params.tab as DetailTab) ? (params.tab as DetailTab) : null;
}

function serverCanonicalPath(serverName: string, tab: DetailTab) {
  const serverPath = `/servers/${serverName.split("/").map(encodeURIComponent).join("/")}`;
  return tab === "overview" ? serverPath : `${serverPath}/${tab}`;
}

async function resolveServerDetailRoute({ fixedTab, params }: ServerDetailTemplateProps) {
  const resolvedParams = await params;
  const serverName = serverNameFromParams(resolvedParams);
  const tab = tabFromParams(resolvedParams, fixedTab);
  if (!tab) notFound();
  return {
    canonical: serverName ? serverCanonicalPath(serverName, tab) : "/servers",
    serverName,
    tab,
  };
}

export async function generateServerDetailMetadata(
  props: ServerDetailTemplateProps,
): Promise<Metadata> {
  const { canonical, serverName } = await resolveServerDetailRoute(props);

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
    const server = await getPublishedRegistryServerSummary(serverName);
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

export async function ServerDetailPageTemplate(props: ServerDetailTemplateProps) {
  const { canonical, serverName, tab } = await resolveServerDetailRoute(props);
  const { initialDetail, initialError } = await (async () => {
    if (!serverName) {
      return { initialDetail: null, initialError: "Server route is incomplete." };
    }
    try {
      return {
        initialDetail: await getPublishedRegistryServerTab(serverName, tab),
        initialError: "",
      };
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
        tab === "overview" ? (
          <JsonLdScript
            data={serverDetailJsonLd(initialDetail, canonical)}
            id="server-detail-json-ld"
          />
        ) : null
      ) : null}
      <ServerDetailClient
        initialDetail={initialDetail}
        initialError={initialError}
        initialTab={tab}
        key={`${serverName}:${tab}`}
        serverName={serverName}
      />
    </>
  );
}
