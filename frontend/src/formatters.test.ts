import { describe, expect, it } from "vitest";

import { formatNumber, formatPercent, riskTone } from "./shared/lib/formatters";

describe("formatters", () => {
  it("formats ratio as percent with two decimals", () => {
    expect(formatPercent(0.12345)).toBe("12.35%");
    expect(formatPercent(null)).toBe("-");
  });

  it("formats numbers with configurable precision", () => {
    expect(formatNumber(1.23456, 3)).toBe("1.235");
    expect(formatNumber(undefined)).toBe("-");
  });

  it("maps risk state to stable UI tone", () => {
    expect(riskTone("REDUCED")).toBe("danger");
    expect(riskTone("NORMAL")).toBe("success");
    expect(riskTone("UNKNOWN")).toBe("neutral");
  });
});
