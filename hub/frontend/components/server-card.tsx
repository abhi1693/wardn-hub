"use client";

import Link from "next/link";

import { ServerIcon, serverIconUrl } from "@/components/server-icon";
import type { RegistryServerRead } from "@/lib/api/generated/model";

export function serverDetailHref(serverName: string) {
  return `/servers/${serverName.split("/").map(encodeURIComponent).join("/")}`;
}

export function ServerCard({ server }: { server: RegistryServerRead }) {
  return (
    <Link className="server-card" href={serverDetailHref(server.name)}>
      <span className="server-card-head">
        <ServerIcon src={serverIconUrl(server)} title={server.title || server.name} />
        <span>
          <strong>{server.title || server.name}</strong>
          <small>{server.categories?.[0]?.name || "MCP Server"}</small>
        </span>
      </span>
      <span className="server-card-description">{server.description}</span>
    </Link>
  );
}
