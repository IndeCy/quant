import { describe, expect, it } from "vitest";

import { validateStrategyDraftWeights } from "./validation";

describe("validateStrategyDraftWeights", () => {
  it("accepts enabled weights whose sum is one", () => {
    expect(
      validateStrategyDraftWeights([
        { factor_id: "roa", weight: 0.7, transform: "zscore", enabled: true },
        { factor_id: "ocf_to_or", weight: 0.3, transform: "zscore", enabled: true }
      ])
    ).toEqual({ valid: true, message: "权重有效" });
  });

  it("rejects empty enabled factors and invalid total weight", () => {
    expect(validateStrategyDraftWeights([]).valid).toBe(false);
    expect(
      validateStrategyDraftWeights([{ factor_id: "roa", weight: 0.8, transform: "zscore", enabled: true }])
    ).toEqual({ valid: false, message: "启用因子权重合计需要等于 1，当前为 0.800" });
  });
});
