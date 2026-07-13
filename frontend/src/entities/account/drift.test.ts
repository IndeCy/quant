import { expect, test } from "vitest";

import { maxDriftLabel, sortAccountPositions } from "./drift";

test("sortAccountPositions prioritizes trade actions and drift", () => {
  const result = sortAccountPositions([
    { symbol: "B", action: "HOLD", drift_weight: 0.01 } as never,
    { symbol: "A", action: "SELL", drift_weight: -0.03 } as never,
    { symbol: "C", action: "BUY", drift_weight: 0.05 } as never
  ]);

  expect(result.map((item) => item.symbol)).toEqual(["C", "A", "B"]);
});

test("maxDriftLabel formats empty and populated snapshots", () => {
  expect(maxDriftLabel(null)).toBe("-");
  expect(maxDriftLabel({ max_abs_drift: 0.1234 } as never)).toBe("12.34%");
});
