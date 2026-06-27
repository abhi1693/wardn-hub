"use client";

import { useState } from "react";

import { ServerCard } from "@/components/server-card";
import { listPublishedServers } from "@/lib/api/hub";
import type { RegistryServerRead } from "@/lib/api/generated/model";
import { PUBLIC_CARD_FIELDS } from "@/lib/registry-fields";

const EXPLORE_PAGE_SIZE = 60;

export function ExploreServerGrid({
  initialNextCursor,
  initialServers,
}: {
  initialNextCursor: string;
  initialServers: RegistryServerRead[];
}) {
  const [servers, setServers] = useState(initialServers);
  const [nextCursor, setNextCursor] = useState(initialNextCursor);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadMore() {
    if (!nextCursor || loading) return;

    setLoading(true);
    setError("");
    try {
      const response = await listPublishedServers({
        cursor: nextCursor,
        fields: PUBLIC_CARD_FIELDS,
        limit: EXPLORE_PAGE_SIZE,
      });
      setServers((current) => [...current, ...response.servers]);
      setNextCursor(response.metadata.nextCursor ?? "");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load more servers.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="server-grid">
        {servers.map((server) => (
          <ServerCard key={server.id} server={server} showQualityScore />
        ))}
      </div>
      {nextCursor || error ? (
        <div className="server-grid-more">
          {error ? <p>{error}</p> : null}
          {nextCursor ? (
            <button className="server-grid-load-more" disabled={loading} onClick={() => void loadMore()}>
              {loading ? "Loading..." : "Load more"}
            </button>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
