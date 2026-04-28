import { getI18nValue } from "../i18n";

export const formatBytes = (bytes: number) => {
  const units = getI18nValue<string[]>("common.labels.bytesUnits");
  if (bytes === 0) return `0 ${units[0]}`;

  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, index);
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
};

const METRIC_LABELS: Record<string, string> = {
  wpm: "Темп",
  pause_percent: "Паузы",
  fillers_per_min: "Паразиты",
  redundancy_percent: "Избыточность",
  pitch_cv: "Интонация",
  eye_contact: "Зрительный контакт",
};

export const formatFloat = (value: number | null | undefined, decimals = 1): string => {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return value.toFixed(decimals);
};

export const formatPercent = (value: number | null | undefined): string => {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${value.toFixed(1)}%`;
};

export const formatPerMin = (value: number | null | undefined): string => {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${value.toFixed(2)}/мин`;
};

export const formatRange = (min: number | null | undefined, max: number | null | undefined, unit = ""): string => {
  if (typeof min !== "number" || typeof max !== "number") return "—";
  return `${min}–${max}${unit ? ` ${unit}` : ""}`;
};

export const formatMetricLabel = (key: string | null | undefined): string => {
  if (!key) return "Метрика";
  return METRIC_LABELS[key] || key;
};
