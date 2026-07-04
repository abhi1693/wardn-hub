import type { Metadata } from "next";
import { notFound } from "next/navigation";

import {
  getPublishedRegistryServerTab,
  isRegistryNotFoundError,
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

const routeTabs = new Set<DetailTab>(["tools", "prompts", "schema", "score"]);

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

function serverMetadataTitle(serverTitle: string, tab: DetailTab) {
  if (tab === "tools") {
    return `${serverTitle} MCP Server Tools`;
  }
  if (tab === "prompts") {
    return `${serverTitle} MCP Server Prompts`;
  }
  if (tab === "schema") {
    return `${serverTitle} MCP Server Schema - Packages, Transports, and Configuration`;
  }
  if (tab === "score") {
    return `${serverTitle} MCP Server Trust Score and Maintenance Signals`;
  }
  return `${serverTitle} MCP Server - Install, Configuration, Packages, and Trust Score`;
}

function serverMetadataDescription(
  serverName: string,
  serverTitle: string,
  tab: DetailTab,
  description?: string,
) {
  if (tab === "overview" && description) return description;
  if (tab === "tools") {
    return `Review ${serverTitle} MCP server tool definitions, parameters, schemas, and annotations on Wardn Hub.`;
  }
  if (tab === "prompts") {
    return `Review ${serverTitle} MCP server prompt templates, arguments, and prompt metadata on Wardn Hub.`;
  }
  if (tab === "schema") {
    return `Review ${serverTitle} MCP server package, transport, schema, and configuration metadata on Wardn Hub.`;
  }
  if (tab === "score") {
    return `Review ${serverTitle} MCP server quality score, trust report, and maintenance signals on Wardn Hub.`;
  }
  return `Review ${serverName} MCP server metadata, installation details, and trust signals on Wardn Hub.`;
}

async function resolveServerDetailRoute({ fixedTab, params }: ServerDetailTemplateProps) {
  const resolvedParams = await params;
  const serverName = serverNameFromParams(resolvedParams);
  const tab = tabFromParams(resolvedParams, fixedTab);
  if (!serverName || !tab) notFound();
  return {
    canonical: serverCanonicalPath(serverName, tab),
    serverName,
    tab,
  };
}

export async function generateServerDetailMetadata(
  props: ServerDetailTemplateProps,
): Promise<Metadata> {
  const { canonical, serverName, tab } = await resolveServerDetailRoute(props);

  try {
    const detail = await getPublishedRegistryServerTab(serverName, tab);
    const serverTitle = detail.server.title || detail.server.name;
    const title = serverMetadataTitle(serverTitle, tab);
    const description = serverMetadataDescription(
      serverName,
      serverTitle,
      tab,
      detail.server.description,
    );

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
  } catch (caught) {
    if (isRegistryNotFoundError(caught)) notFound();
    const title = serverMetadataTitle(serverName, tab);
    return {
      alternates: {
        canonical,
      },
      robots: {
        follow: false,
        index: false,
      },
      title,
      twitter: {
        card: "summary",
        title: `${title} | ${siteConfig.name}`,
      },
    };
  }
}

export async function ServerDetailPageTemplate(props: ServerDetailTemplateProps) {
  const { canonical, serverName, tab } = await resolveServerDetailRoute(props);
  const { initialDetail, initialError } = await (async () => {
    try {
      return {
        initialDetail: await getPublishedRegistryServerTab(serverName, tab),
        initialError: "",
      };
    } catch (caught) {
      if (isRegistryNotFoundError(caught)) notFound();
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
