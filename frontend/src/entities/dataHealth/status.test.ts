import { describe, expect, it } from "vitest";

import { healthTone } from "./status";

describe("healthTone", () => {
  it("marks existing sections with aligned dates as success", () => {
    expect(healthTone(true, ["20260624", "20260624"])).toBe("success");
  });

  it("marks missing files or mismatched dates as danger", () => {
    expect(healthTone(false, ["20260624"])).toBe("danger");
    expect(healthTone(true, ["20260624", "20260623"])).toBe("danger");
  });
});
