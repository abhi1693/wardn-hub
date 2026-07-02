export const QUALITY_SCORE_METHODOLOGY_PATH = "/methodology/quality-score";

export type RegistryFacts = {
  categoryCount: number | null;
  generatedAt: string;
  lastRegistryUpdate: string | null;
  methodologyPath: string;
  publishedServerCount: number | null;
  scannedServerCount: number;
};

export function formatFactDate(value: string | null) {
  if (!value) return "Unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unavailable";
  return new Intl.DateTimeFormat("en", {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(date);
}
