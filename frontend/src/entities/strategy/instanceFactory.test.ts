import { describe, expect, it } from "vitest";

import { buildFactorTopNInstance, createEditableFactors, validateEditableFactors } from "./instanceFactory";

describe("strategy instance factory", () => {
  it("creates editable factors from available factor catalog", () => {
    const factors = createEditableFactors([
      { factor_id: "roa", name: "ROA", category: "quality", direction: "higher", enabled: true, config: {}, strategies: [] },
      { factor_id: "ocf", name: "OCF", category: "quality", direction: "higher", enabled: true, config: {}, strategies: [] }
    ]);

    expect(factors).toEqual([
      { factor_id: "roa", weight: 1, transform: "winsorize_zscore", enabled: true },
      { factor_id: "ocf", weight: 0, transform: "winsorize_zscore", enabled: false }
    ]);
  });

  it("validates enabled factor weights before creating runnable instances", () => {
    expect(validateEditableFactors([])).toEqual({ valid: false, message: "至少需要启用一个因子" });
    expect(validateEditableFactors([{ factor_id: "roa", weight: 0.5, transform: "zscore", enabled: true }]).valid).toBe(false);
    expect(validateEditableFactors([{ factor_id: "roa", weight: 1, transform: "zscore", enabled: true }])).toEqual({
      valid: true,
      message: "权重有效"
    });
  });

  it("builds a factor TopN strategy instance payload", () => {
    const payload = buildFactorTopNInstance({
      strategyId: "quality_roa_v2",
      name: "Quality ROA V2",
      status: "paper",
      enabled: true,
      factors: [
        { factor_id: "roa", weight: 0.7, transform: "winsorize_zscore", enabled: true },
        { factor_id: "roe", weight: 0.3, transform: "winsorize_zscore", enabled: true },
        { factor_id: "ocf", weight: 0, transform: "winsorize_zscore", enabled: false }
      ],
      topN: 20,
      benchmark: "510300",
      riskOverlay: "vol_20_45_to_30"
    });

    expect(payload.template_id).toBe("factor_topn_monthly");
    expect(payload.factors.map((factor) => factor.factor_id)).toEqual(["roa", "roe"]);
    expect(payload.construction.top_n).toBe(20);
  });
});
