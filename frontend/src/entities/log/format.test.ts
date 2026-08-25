import { describe, expect, it } from "vitest";

import { logTypeLabel } from "./format";

describe("logTypeLabel", () => {
  it("maps runtime log types to Chinese labels", () => {
    expect(logTypeLabel("run")).toBe("流水线");
    expect(logTypeLabel("service")).toBe("服务");
    expect(logTypeLabel("other")).toBe("other");
  });
});
