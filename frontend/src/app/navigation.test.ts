import { describe, expect, it } from "vitest";

import { navigationItems } from "./navigation";

describe("navigationItems", () => {
  it("keeps the first stage console pages in stable order", () => {
    expect(navigationItems.map((item) => item.path)).toEqual([
      "/",
      "/market",
      "/strategies",
      "/factors",
      "/runs",
      "/scheduler",
      "/logs",
      "/reports",
      "/research",
      "/data",
      "/risk",
      "/settings"
    ]);
  });

  it("uses short readable labels for sidebar", () => {
    expect(navigationItems.map((item) => item.label)).toEqual([
      "总览",
      "大盘",
      "策略",
      "因子",
      "运行",
      "调度",
      "日志",
      "报告",
      "研究",
      "数据",
      "风险",
      "设置"
    ]);
  });
});
