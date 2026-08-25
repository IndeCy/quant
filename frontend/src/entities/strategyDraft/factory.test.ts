import { describe, expect, it } from "vitest";

import { createDraftFactorsFromAvailableFactors, createDraftFactorsFromStrategy } from "./factory";

describe("createDraftFactorsFromStrategy", () => {
  it("copies factor weights and transforms from an existing strategy", () => {
    const factors = createDraftFactorsFromStrategy([
      { factor_id: "roa", name: "ROA", weight: 0.5, transform: "winsorize_zscore", enabled: true },
      { factor_id: "ocf_to_or", name: "OCF", weight: 0.3, transform: "winsorize_zscore", enabled: false },
      { factor_id: "roe", name: "ROE", weight: 0.2 }
    ]);

    expect(factors).toEqual([
      { factor_id: "roa", weight: 0.5, transform: "winsorize_zscore", enabled: true },
      { factor_id: "ocf_to_or", weight: 0.3, transform: "winsorize_zscore", enabled: false },
      { factor_id: "roe", weight: 0.2, transform: "winsorize_zscore", enabled: true }
    ]);
  });

  it("uses the factor registry as the editable universe and disables unused factors", () => {
    const factors = createDraftFactorsFromAvailableFactors(
      [
        { factor_id: "roa", name: "ROA" },
        { factor_id: "roe", name: "ROE" },
        { factor_id: "new_quality", name: "New Quality" }
      ],
      [{ factor_id: "roa", weight: 1, transform: "winsorize_zscore", enabled: true }]
    );

    expect(factors).toEqual([
      { factor_id: "roa", weight: 1, transform: "winsorize_zscore", enabled: true },
      { factor_id: "roe", weight: 0, transform: "winsorize_zscore", enabled: false },
      { factor_id: "new_quality", weight: 0, transform: "winsorize_zscore", enabled: false }
    ]);
  });
});
