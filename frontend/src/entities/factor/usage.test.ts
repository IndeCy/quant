import { describe, expect, it } from "vitest";

import type { FactorDefinition } from "./model";
import { factorUsageLabel, factorWeightSum } from "./usage";

describe("factor usage helpers", () => {
  it("summarizes enabled strategy usage for a factor", () => {
    const factor: FactorDefinition = {
      factor_id: "roa",
      name: "ROA",
      category: "quality",
      direction: "higher_is_better",
      enabled: true,
      strategies: [
        { strategy_id: "quality_overlay", name: "Quality Alpha V1", status: "active", weight: 0.6, transform: "zscore", enabled: true },
        { strategy_id: "draft", name: "Draft", status: "draft", weight: 0.4, transform: "zscore", enabled: false }
      ]
    };

    expect(factorUsageLabel(factor)).toBe("1 个启用策略");
    expect(factorWeightSum(factor)).toBe(0.6);
  });

  it("marks unused factors clearly", () => {
    expect(
      factorUsageLabel({
        factor_id: "roe",
        name: "ROE",
        category: "quality",
        direction: "higher_is_better",
        enabled: true,
        strategies: []
      })
    ).toBe("未被策略使用");
  });
});
