import { describe, expect, it } from "vitest";

import { dataFreshnessSummary, healthTone } from "./status";

describe("healthTone", () => {
  it("marks existing sections with aligned dates as success", () => {
    expect(healthTone(true, ["20260624", "20260624"])).toBe("success");
  });

  it("marks missing files or mismatched dates as danger", () => {
    expect(healthTone(false, ["20260624"])).toBe("danger");
    expect(healthTone(true, ["20260624", "20260623"])).toBe("danger");
  });
});

describe("dataFreshnessSummary", () => {
  it("marks all sections aligned when every date is the same", () => {
    const summary = dataFreshnessSummary({
      runtime_root: "/tmp/runtime",
      live_market_increment: {
        path: "/tmp/daily.duckdb",
        exists: true,
        latest_daily_date: "20260629",
        latest_adj_factor_date: "20260629"
      },
      benchmark_increment: {
        path: "/tmp/benchmark.duckdb",
        exists: true,
        latest_fund_date: "20260629",
        latest_fund_adj_date: "20260629",
        latest_index_date: "20260629"
      },
      monitoring: { path: "/tmp/monitoring.sqlite3", exists: true, latest_strategy_date: "20260629", latest_market_date: "20260629" },
      system_state: { path: "/tmp/state.sqlite", exists: true, latest_run_date: "20260629", latest_report_date: "20260629" }
    });

    expect(summary).toEqual({ tone: "success", label: "全部对齐", latestDate: "20260629" });
  });

  it("reports date mismatch and missing sections", () => {
    expect(
      dataFreshnessSummary({
        runtime_root: "/tmp/runtime",
        live_market_increment: { path: "/tmp/daily.duckdb", exists: true, latest_daily_date: "20260629", latest_adj_factor_date: "20260628" },
        benchmark_increment: { path: "/tmp/benchmark.duckdb", exists: true, latest_fund_date: "20260629" },
        monitoring: { path: "/tmp/monitoring.sqlite3", exists: true },
        system_state: { path: "/tmp/state.sqlite", exists: true }
      }).label
    ).toBe("日期不一致");
    expect(
      dataFreshnessSummary({
        runtime_root: "/tmp/runtime",
        live_market_increment: { path: "/tmp/daily.duckdb", exists: false },
        benchmark_increment: { path: "/tmp/benchmark.duckdb", exists: true },
        monitoring: { path: "/tmp/monitoring.sqlite3", exists: true },
        system_state: { path: "/tmp/state.sqlite", exists: true }
      }).label
    ).toBe("存在缺失");
  });
});
