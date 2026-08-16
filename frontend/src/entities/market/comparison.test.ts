import { describe, expect, it } from "vitest";

import type { MarketIndexComparison } from "./model";
import { buildMarketIndexComparisonLines } from "./comparison";

const comparison: MarketIndexComparison = {
  data_status: "READY",
  as_of: "20260703",
  adjust_policy: "index_raw",
  indices: [
    {
      symbol: "000001.SH",
      name: "上证指数",
      points: [
        { trade_date: "20260702", nav: 1.2 },
        { trade_date: "20260703", nav: 1.26 }
      ]
    },
    {
      symbol: "000300.SH",
      name: "沪深300",
      points: [
        { trade_date: "20260701", nav: 0.8 },
        { trade_date: "20260702", nav: 0.84 },
        { trade_date: "20260703", nav: 0.82 }
      ]
    },
    {
      symbol: "nasdaq_gold_60_40_sp500_hurdle_v3",
      name: "纳指黄金60/40（V3）",
      series_kind: "research",
      adjust_policy: "qfq_m0_t1_5bps",
      points: [
        { trade_date: "20260701", nav: 2 },
        { trade_date: "20260702", nav: 2.1 },
        { trade_date: "20260703", nav: 2.2 }
      ]
    }
  ]
};

describe("market index comparison", () => {
  it("aligns both indices to chart dates and rebases each visible window", () => {
    const lines = buildMarketIndexComparisonLines(comparison, ["20260701", "20260702", "20260703"]);

    expect(lines[0].name).toBe("上证指数");
    expect(Number.isNaN(lines[0].data[0])).toBe(true);
    expect(lines[0].data[1]).toBe(1);
    expect(lines[0].data[2]).toBeCloseTo(1.05);
    expect(lines[1].name).toBe("沪深300");
    expect(lines[1].data[0]).toBeCloseTo(1);
    expect(lines[1].data[1]).toBeCloseTo(1.05);
    expect(lines[1].data[2]).toBeCloseTo(1.025);
    expect(lines[2].name).toBe("纳指黄金60/40（V3）");
    expect(lines[2].data).toEqual([1, 1.05, 1.1]);
  });

  it("drops indices without observations in the selected window", () => {
    expect(buildMarketIndexComparisonLines(comparison, ["20250101"])).toEqual([]);
  });
});
