"use client";

import { useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
  type DotItemDotProps,
} from "recharts";

import type {
  SkillAuditHistoryEntryRead,
  SkillAuditHistoryResponse,
} from "@/lib/api/generated/model";

const GRADE_THRESHOLD = 75;

type AuditChartEntry = SkillAuditHistoryEntryRead & {
  change: number | null;
  dateCompact: string;
  dateFull: string;
};

type ActiveAuditPoint = {
  alignment: "center" | "end" | "start";
  entry: AuditChartEntry;
  placement: "above" | "below";
  x: number;
  y: number;
};

function formatDate(value: string, compact = false) {
  return new Intl.DateTimeFormat("en-US", {
    day: "numeric",
    month: compact ? "short" : "long",
    timeZone: "UTC",
    year: compact ? "2-digit" : "numeric",
  }).format(new Date(value));
}

function scoreChange(
  entry: SkillAuditHistoryEntryRead,
  entries: SkillAuditHistoryEntryRead[],
) {
  const index = entries.indexOf(entry);
  const previous = entries[index + 1];
  return previous ? entry.score - previous.score : null;
}

function changeLabel(change: number | null) {
  if (change === null) return "—";
  if (change > 0) return `+${change}`;
  return String(change);
}

function decisionLabel(status: SkillAuditHistoryEntryRead["status"]) {
  return status === "warn" ? "Review" : `${status[0]?.toUpperCase()}${status.slice(1)}`;
}

function AuditScoreDot({
  onActivate,
  onDeactivate,
  ...props
}: DotItemDotProps & {
  onActivate: (point: ActiveAuditPoint) => void;
  onDeactivate: () => void;
}) {
  const entry = props.payload as AuditChartEntry;
  const { cx, cy } = props;
  if (typeof cx !== "number" || typeof cy !== "number") return null;
  const chartRight = Math.max(
    ...props.points.map((point) => (typeof point.x === "number" ? point.x : 0)),
  );
  const point = {
    alignment:
      props.points.length === 1
        ? "center"
        : cx < 120
          ? "start"
          : cx > chartRight - 120
            ? "end"
            : "center",
    entry,
    placement: cy < 120 ? "below" : "above",
    x: cx,
    y: cy,
  } satisfies ActiveAuditPoint;
  const label = `${entry.dateFull}: ${entry.score} out of 100, grade ${entry.rank}, ${decisionLabel(entry.status)}${entry.current ? ", current snapshot" : ""}`;
  return (
    <g
      aria-label={label}
      className="skill-audit-history-dot-target"
      onBlur={onDeactivate}
      onFocus={() => onActivate(point)}
      onMouseEnter={() => onActivate(point)}
      onMouseLeave={onDeactivate}
      role="img"
      tabIndex={0}
    >
      <circle className="skill-audit-history-dot-hit-area" cx={cx} cy={cy} r={14} />
      {entry.current ? (
        <circle className="skill-audit-history-current-ring" cx={cx} cy={cy} r={10} />
      ) : null}
      <circle
        className={`skill-audit-history-score-dot ${entry.status}`}
        cx={cx}
        cy={cy}
        r={5}
      />
    </g>
  );
}

function AuditHistoryTooltip({ entry }: { entry: AuditChartEntry }) {
  return (
    <div
      aria-live="polite"
      className={`skill-audit-history-tooltip ${entry.status}`}
      role="status"
    >
      <header>
        <span className={`skill-audit-history-decision ${entry.status}`}>
          {decisionLabel(entry.status)}
        </span>
        {entry.current ? <span className="skill-audit-history-current">Current</span> : null}
      </header>
      <time dateTime={entry.publishedAt}>{entry.dateFull}</time>
      <div className="skill-audit-history-tooltip-score">
        <strong>{entry.score}</strong>
        <span>/100</span>
        <span className={`skill-audit-history-grade ${entry.status}`}>{entry.rank}</span>
      </div>
      <dl>
        <div>
          <dt>Snapshot</dt>
          <dd>
            <code>{entry.contentHash.slice(0, 10)}</code>
          </dd>
        </div>
        <div>
          <dt>Change</dt>
          <dd>{changeLabel(entry.change)}</dd>
        </div>
      </dl>
    </div>
  );
}

export function SkillAuditHistory({
  history,
}: {
  history: SkillAuditHistoryResponse | null;
}) {
  const [activePoint, setActivePoint] = useState<ActiveAuditPoint | null>(null);
  const newestFirst = history?.data ?? [];
  if (!newestFirst.length) return null;

  const entries = [...newestFirst].reverse();
  const chartEntries: AuditChartEntry[] = entries.map((entry) => ({
    ...entry,
    change: scoreChange(entry, newestFirst),
    dateCompact: formatDate(entry.publishedAt, true),
    dateFull: formatDate(entry.publishedAt),
  }));

  return (
    <section className="skill-audit-history" aria-labelledby="skill-audit-history-heading">
      <header>
        <div>
          <span className="registry-hero-eyebrow">Trust over time</span>
          <h2 id="skill-audit-history-heading">Score history</h2>
          <p>
            Each point is an audited content snapshot. Color reflects the risk decision; the score
            shows how the bundle changed between retained versions.
          </p>
        </div>
      </header>

      <div
        aria-describedby="skill-audit-history-chart-description"
        className="skill-audit-history-chart"
      >
        <p className="skill-audit-history-chart-description" id="skill-audit-history-chart-description">
          Scores range from zero to one hundred. Use Tab and arrow keys to inspect each snapshot.
          Dots are green for pass, amber for review, and red for fail.
        </p>
        <div className="skill-audit-history-chart-canvas">
          <ResponsiveContainer height={250} width="100%">
            <LineChart
              accessibilityLayer
              data={chartEntries}
              margin={{ bottom: 8, left: 0, right: 12, top: 12 }}
            >
              <CartesianGrid stroke="var(--border)" strokeDasharray="2 4" vertical={false} />
              <XAxis
                axisLine={false}
                dataKey="dateCompact"
                interval="preserveStartEnd"
                minTickGap={42}
                tick={{ fill: "var(--muted-foreground)", fontSize: 10, fontWeight: 650 }}
                tickLine={false}
              />
              <YAxis
                axisLine={false}
                domain={[0, 100]}
                tick={{ fill: "var(--muted-foreground)", fontSize: 10, fontWeight: 650 }}
                tickLine={false}
                ticks={[0, 25, 50, 75, 100]}
                width={36}
              />
              <ReferenceLine
                label={{
                  fill: "var(--electric-blue)",
                  fontSize: 10,
                  fontWeight: 750,
                  position: "insideTopRight",
                  value: `A threshold · ${GRADE_THRESHOLD}`,
                }}
                stroke="var(--electric-blue)"
                strokeDasharray="4 4"
                strokeOpacity={0.72}
                y={GRADE_THRESHOLD}
              />
              <Line
                activeDot={false}
                dataKey="score"
                dot={(props: DotItemDotProps) => (
                  <AuditScoreDot
                    {...props}
                    onActivate={setActivePoint}
                    onDeactivate={() => setActivePoint(null)}
                  />
                )}
                isAnimationActive={false}
                name="Audit score"
                stroke="var(--electric-blue)"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                type="monotone"
              />
            </LineChart>
          </ResponsiveContainer>
          {activePoint ? (
            <div
              className={`skill-audit-history-tooltip-anchor ${activePoint.alignment} ${activePoint.placement}`}
              style={{ left: activePoint.x, top: activePoint.y }}
            >
              <AuditHistoryTooltip entry={activePoint.entry} />
            </div>
          ) : null}
        </div>
      </div>

      <div className="skill-audit-history-table-shell">
        <table className="skill-audit-history-table">
          <thead>
            <tr>
              <th scope="col">Snapshot</th>
              <th scope="col">Published</th>
              <th scope="col">Decision</th>
              <th scope="col">Grade</th>
              <th scope="col">Score</th>
              <th scope="col">Change</th>
            </tr>
          </thead>
          <tbody>
            {newestFirst.map((entry) => {
              const change = scoreChange(entry, newestFirst);
              return (
                <tr key={entry.contentHash}>
                  <td data-label="Snapshot">
                    <code title={entry.contentHash}>{entry.contentHash.slice(0, 10)}</code>
                    {entry.current ? <span className="skill-audit-history-current">Current</span> : null}
                  </td>
                  <td data-label="Published">
                    <time dateTime={entry.publishedAt}>{formatDate(entry.publishedAt)}</time>
                  </td>
                  <td data-label="Decision">
                    <span className={`skill-audit-history-decision ${entry.status}`}>
                      {entry.status === "warn" ? "Review" : entry.status}
                    </span>
                  </td>
                  <td data-label="Grade">
                    <span className={`skill-audit-history-grade ${entry.status}`}>{entry.rank}</span>
                  </td>
                  <td data-label="Score">
                    <strong>{entry.score}</strong>
                    <span className="skill-audit-history-score-total">/100</span>
                  </td>
                  <td
                    className={
                      change === null
                        ? ""
                        : change > 0
                          ? "skill-audit-history-change-up"
                          : change < 0
                            ? "skill-audit-history-change-down"
                            : ""
                    }
                    data-label="Change"
                  >
                    {changeLabel(change)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="skill-audit-history-footnote">
        History begins with the earliest retained audit. Audit status is risk-based and remains the
        security decision even when scores are similar.
      </p>
    </section>
  );
}
