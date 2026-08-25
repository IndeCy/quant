import { describe, expect, it } from "vitest";

import { serviceStatusLabel } from "./status";

describe("serviceStatusLabel", () => {
  it("maps service running state to readable label", () => {
    expect(serviceStatusLabel(true)).toBe("运行中");
    expect(serviceStatusLabel(false)).toBe("未运行");
  });
});
