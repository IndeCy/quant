import { describe, expect, it } from "vitest";

import { hotMoneyStatusLabel } from "./hotMoney";

describe("hotMoneyStatusLabel", () => {
  it("explains ready and missing cache states for the research page", () => {
    expect(hotMoneyStatusLabel("READY")).toBe("已生成");
    expect(hotMoneyStatusLabel("MISSING_CACHE")).toBe("缺少缓存");
  });
});
