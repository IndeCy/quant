import { describe, expect, it } from "vitest";

import { navigationItems } from "./navigation";

describe("navigationItems", () => {
  it("keeps the first stage console pages in stable order", () => {
    expect(navigationItems.map((item) => item.path)).toEqual([
      "/",
      "/strategies",
      "/factors",
      "/runs",
      "/reports",
      "/data",
      "/risk",
      "/settings"
    ]);
  });

  it("uses short readable labels for sidebar", () => {
    expect(navigationItems.map((item) => item.label)).toEqual([
      "总览",
      "策略",
      "因子",
      "运行",
      "报告",
      "数据",
      "风险",
      "设置"
    ]);
  });
});
