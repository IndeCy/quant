import { expect, test } from "vitest";

import { lifecycleTone, transitionCandidates } from "./lifecycle";

test("transitionCandidates follows lifecycle sequence", () => {
  expect(transitionCandidates("research").map((item) => item.target_status)).toEqual(["paper", "paused", "retired"]);
});

test("transitionCandidates includes pause and retire for runnable states", () => {
  expect(transitionCandidates("paper").map((item) => item.target_status)).toEqual(["shadow_live", "paused", "retired"]);
});

test("transitionCandidates supports research observation status", () => {
  expect(transitionCandidates("research_observation").map((item) => item.target_status)).toEqual(["paper", "paused", "retired"]);
});

test("lifecycleTone treats research observation as neutral", () => {
  expect(lifecycleTone("research_observation")).toBe("neutral");
});
