import { describe, expect, it } from "vitest";

import { readinessTone, readinessTitle } from "./status";

describe("readiness status helpers", () => {
  it("maps overall readiness to local dashboard labels", () => {
    expect(readinessTitle("READY")).toBe("可连续运行");
    expect(readinessTone("READY")).toBe("success");
    expect(readinessTitle("NOT_READY")).toBe("需要处理");
    expect(readinessTone("NOT_READY")).toBe("danger");
  });
});
