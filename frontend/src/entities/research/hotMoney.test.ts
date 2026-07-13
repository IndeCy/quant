import { describe, expect, it } from "vitest";

import { formatHotMoneyTradeDate, hotMoneyStatusLabel } from "./hotMoney";

describe("hotMoneyStatusLabel", () => {
  it("explains ready and missing cache states for the research page", () => {
    expect(hotMoneyStatusLabel("READY")).toBe("已生成");
    expect(hotMoneyStatusLabel("MISSING_CACHE")).toBe("缺少缓存");
  });

  it("formats compact trade dates for explicit cache date display", () => {
    expect(formatHotMoneyTradeDate("20260706")).toBe("2026-07-06");
    expect(formatHotMoneyTradeDate("")).toBe("-");
  });
});
