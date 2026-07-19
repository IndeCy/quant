export type ChartValueType = "number" | "percent" | "integer";

export const CHART_COLORS = {
  blue: "#2563eb",
  amber: "#ca8a04",
  red: "#dc2626",
  green: "#0f9f6e",
  slate: "#475569",
  cyan: "#0891b2",
  rose: "#be123c"
} as const;

const SERIES_PALETTE = [
  CHART_COLORS.blue,
  CHART_COLORS.amber,
  CHART_COLORS.green,
  CHART_COLORS.red,
  CHART_COLORS.slate,
  CHART_COLORS.cyan,
  CHART_COLORS.rose
];

export function calculateZoomStart(total: number, visibleCount = 120): number {
  if (total <= visibleCount || total <= 0) return 0;
  return ((total - visibleCount) / total) * 100;
}

export function normalizeChartData(values: Array<number | null | undefined>): Array<number | null> {
  return values.map((value) => (typeof value === "number" && Number.isFinite(value) ? value : null));
}

export function resolveSeriesColor(name: string, index: number): string {
  const normalized = name.toUpperCase();
  if (normalized.includes("MA5")) return CHART_COLORS.blue;
  if (normalized.includes("MA10") || normalized.includes("波动")) return CHART_COLORS.amber;
  if (normalized.includes("MA20") || normalized.includes("回撤") || normalized.includes("涨停") || normalized.includes("新高")) {
    return CHART_COLORS.red;
  }
  if (normalized.includes("MA60") || normalized.includes("跌停") || normalized.includes("新低")) return CHART_COLORS.green;
  if (normalized.includes("MA120") || normalized.includes("基准")) return CHART_COLORS.slate;
  if (normalized.includes("超额")) return CHART_COLORS.cyan;
  return SERIES_PALETTE[index % SERIES_PALETTE.length];
}

export function formatChartValue(value: number, valueType: ChartValueType = "number"): string {
  if (!Number.isFinite(value)) return "-";
  if (valueType === "percent") return `${(value * 100).toFixed(2)}%`;
  if (valueType === "integer") return Math.round(value).toLocaleString("zh-CN");
  return value.toFixed(2);
}

export function formatChartAxisValue(value: number, valueType: ChartValueType = "number"): string {
  if (!Number.isFinite(value)) return "-";
  if (valueType === "percent") return `${(value * 100).toFixed(1)}%`;
  if (valueType === "integer") return Math.round(value).toLocaleString("zh-CN");
  const absolute = Math.abs(value);
  return value.toFixed(absolute >= 100 ? 0 : absolute >= 10 ? 1 : 2);
}

export function buildChartRangeLabel(dates: string[]): string {
  if (dates.length === 0) return "暂无数据";
  const first = formatTradeDate(dates[0]);
  const last = formatTradeDate(dates[dates.length - 1]);
  if (dates.length === 1) return last;
  return `${first} - ${last} · ${dates.length}日`;
}

function formatTradeDate(value: string): string {
  if (!/^\d{8}$/.test(value)) return value;
  return `${value.slice(0, 4)}.${value.slice(4, 6)}.${value.slice(6, 8)}`;
}
