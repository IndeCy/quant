import { describe, expect, it } from "vitest";

import { relativeStyleDisplay, trendStyleDisplay } from "./styleDisplay";

describe("market style display", () => {
  it("maps trend states to stable Chinese references", () => {
    expect(trendStyleDisplay("UP")).toEqual({ label: "多头结构", tone: "success" });
    expect(trendStyleDisplay("DOWN")).toEqual({ label: "空头结构", tone: "danger" });
    expect(trendStyleDisplay("INSUFFICIENT").label).toBe("样本不足");
  });

  it("explains relative strength with a fixed 3% reference", () => {
    expect(relativeStyleDisplay("MICRO_STRONG")).toEqual({ label: "微盘相对占优", tone: "success" });
    expect(relativeStyleDisplay("LARGE_STRONG")).toEqual({ label: "大盘相对占优", tone: "warning" });
    expect(relativeStyleDisplay("BALANCED").label).toBe("风格均衡");
  });
});
