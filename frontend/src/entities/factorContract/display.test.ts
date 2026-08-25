import { expect, test } from "vitest";

import { asOfLabel, contractStatusLabel } from "./display";

test("contractStatusLabel distinguishes contract availability", () => {
  expect(contractStatusLabel(null)).toBe("无契约");
  expect(contractStatusLabel({ factor_id: "roa", status: "active" } as never)).toBe("有契约");
});

test("asOfLabel renders financial announcement field", () => {
  expect(asOfLabel({ as_of_policy: "financial_announcement", as_of_field: "f_ann_date" } as never)).toBe(
    "financial_announcement / f_ann_date"
  );
});
