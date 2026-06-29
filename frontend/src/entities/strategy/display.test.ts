import { describe, expect, it } from "vitest";

import { strategyMetricText } from "./display";

describe("strategyMetricText", () => {
  it("uses dash for strategies without metrics", () => {
    expect(strategyMetricText(null, "trade_date")).toBe("-");
    expect(strategyMetricText(undefined, "cumulative_return")).toBe("-");
  });

  it("formats available strategy metrics", () => {
    expect(strategyMetricText({ trade_date: "20260629", cumulative_return: 0.12, drawdown: -0.05 }, "trade_date")).toBe("20260629");
    expect(strategyMetricText({ trade_date: "20260629", cumulative_return: 0.12, drawdown: -0.05 }, "cumulative_return")).toBe("12.00%");
    expect(strategyMetricText({ trade_date: "20260629", cumulative_return: 0.12, drawdown: -0.05 }, "drawdown")).toBe("-5.00%");
  });
});
