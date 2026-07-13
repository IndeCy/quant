import { describe, expect, it } from "vitest";

import { runStepTone } from "./status";

describe("runStepTone", () => {
  it("maps pipeline step statuses to dashboard tones", () => {
    expect(runStepTone("SUCCESS")).toBe("success");
    expect(runStepTone("WARNING")).toBe("warning");
    expect(runStepTone("FAILED")).toBe("failed");
    expect(runStepTone("SKIPPED")).toBe("skipped");
    expect(runStepTone("UNKNOWN")).toBe("neutral");
  });
});
