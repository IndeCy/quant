import { expect, test } from "vitest";

import { transitionCandidates } from "./lifecycle";

test("transitionCandidates follows lifecycle sequence", () => {
  expect(transitionCandidates("research").map((item) => item.target_status)).toEqual(["paper", "paused", "retired"]);
});

test("transitionCandidates includes pause and retire for runnable states", () => {
  expect(transitionCandidates("paper").map((item) => item.target_status)).toEqual(["shadow_live", "paused", "retired"]);
});
