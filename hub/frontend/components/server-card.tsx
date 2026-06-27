"use client";

import Link from "next/link";

import { ServerIcon, serverIconUrl } from "@/components/server-icon";
import type { RegistryServerRead } from "@/lib/api/generated/model";

export function serverDetailHref(serverName: string) {
  return `/servers/${serverName.split("/").map(encodeURIComponent).join("/")}`;
}

function qualityScoreTone(score: number | null | undefined) {
  if (typeof score !== "number") return "pending";
  if (score >= 85) return "excellent";
  if (score >= 70) return "good";
  if (score >= 50) return "fair";
  return "poor";
}

function qualityScorePercent(score: number | null | undefined) {
  if (typeof score !== "number") return 0;
  return Math.max(0, Math.min(100, score));
}

function QualityScoreMeter({ score }: { score?: number | null }) {
  const value = typeof score === "number" ? `${score}/100` : "Pending";
  const percent = qualityScorePercent(score);

  return (
    <span
      aria-label={`Wardn Score: ${value}`}
      className={`server-card-score-meter ${qualityScoreTone(score)}`}
      title={`Wardn Score: ${value}`}
    >
      <span className="server-card-score-row">
        <span>Quality score</span>
        <span className="server-card-score-value">{value}</span>
      </span>
      <span className="server-card-score-track">
        <span className="server-card-score-fill" style={{ width: `${percent}%` }} />
      </span>
    </span>
  );
}

export function ServerCard({
  server,
  showQualityScore = false,
}: {
  server: RegistryServerRead;
  showQualityScore?: boolean;
}) {
  const categoryName = server.categories?.[0]?.name;

  return (
    <Link className="server-card" href={serverDetailHref(server.name)}>
      <span className="server-card-head">
        <ServerIcon src={serverIconUrl(server)} title={server.title || server.name} />
        <span className="server-card-title-block">
          <strong>{server.title || server.name}</strong>
          {categoryName ? <small>{categoryName}</small> : null}
        </span>
      </span>
      <span className="server-card-description">{server.description}</span>
      {showQualityScore ? (
        <span className="server-card-footer">
          <QualityScoreMeter score={server.qualityScore} />
        </span>
      ) : null}
    </Link>
  );
}
