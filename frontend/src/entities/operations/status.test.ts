import { describe, expect, it } from "vitest";

import { observationStatusTone } from "./status";

describe("operations observation status helpers", () => {
  it("maps observation status to UI tone", () => {
    expect(observationStatusTone("PASS")).toBe("success");
    expect(observationStatusTone("WARN")).toBe("warning");
    expect(observationStatusTone("FAIL")).toBe("danger");
    expect(observationStatusTone("UNKNOWN")).toBe("neutral");
  });
});
