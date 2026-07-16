import { describe, expect, it } from "vitest";

import type { StrategyMetric } from "./model";
import { buildPaperWindow } from "./paperWindow";

function metric(tradeDate: string, nav: number, benchmarkNav: number, paperNav?: number): StrategyMetric {
  return {
    trade_date: tradeDate,
    strategy_id: "quality_overlay",
    nav,
    paper_nav: paperNav,
    daily_return: 0,
    cumulative_return: nav - 1,
    benchmark_id: "510300",
    benchmark_nav: benchmarkNav,
    benchmark_return: 0,
    excess_return: 0,
    drawdown: 0,
    max_drawdown: 0,
    volatility_20: 0,
    volatility_60: 0,
    sharpe_rolling: 0,
    exposure: 1,
    total_execution_cost: 0,
    failed_order_count: 0
  };
}

describe("buildPaperWindow", () => {
  it("只保留Paper日期，并把三条净值归一到同一起点", () => {
    const result = buildPaperWindow([
      metric("20260708", 4.8, 1.58),
      metric("20260709", 5, 1.6, 1),
      metric("20260710", 5.1, 1.616, 0.99)
    ]);

    expect(result.dates).toEqual(["20260709", "20260710"]);
    expect(result.paperNav).toEqual([1, 0.99]);
    expect(result.theoreticalNav).toEqual([1, 1.02]);
    expect(result.benchmarkNav).toEqual([1, 1.01]);
  });

  it("没有Paper快照时返回空窗口", () => {
    expect(buildPaperWindow([metric("20260708", 4.8, 1.58)])).toEqual({
      dates: [],
      paperNav: [],
      theoreticalNav: [],
      benchmarkNav: []
    });
  });
});
