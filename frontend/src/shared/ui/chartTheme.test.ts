import { describe, expect, it } from "vitest";

import {
  CHART_COLORS,
  calculateZoomStart,
  formatChartAxisValue,
  formatChartValue,
  normalizeChartData,
  resolveSeriesColor
} from "./chartTheme";

describe("chart theme", () => {
  it("opens long series at the latest 120 observations", () => {
    expect(calculateZoomStart(240)).toBe(50);
    expect(calculateZoomStart(120)).toBe(0);
    expect(calculateZoomStart(0)).toBe(0);
  });

  it("keeps missing observations as chart gaps", () => {
    expect(normalizeChartData([1, Number.NaN, Number.POSITIVE_INFINITY, null])).toEqual([1, null, null, null]);
  });

  it("formats percent, integer and normal values consistently", () => {
    expect(formatChartValue(0.12345, "percent")).toBe("12.35%");
    expect(formatChartAxisValue(-0.086, "percent")).toBe("-8.6%");
    expect(formatChartValue(72.4, "integer")).toBe("72");
    expect(formatChartValue(1.2345, "number")).toBe("1.23");
  });

  it("uses stable financial semantics for series colors", () => {
    expect(resolveSeriesColor("当前回撤", 0)).toBe(CHART_COLORS.red);
    expect(resolveSeriesColor("MA60", 1)).toBe(CHART_COLORS.green);
    expect(resolveSeriesColor("基准", 2)).toBe(CHART_COLORS.slate);
    expect(resolveSeriesColor("510300净值", 0)).toBe(CHART_COLORS.blue);
  });
});
