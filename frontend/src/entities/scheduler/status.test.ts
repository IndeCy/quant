import { describe, expect, it } from "vitest";

import { schedulerStateLabel, schedulerNextRunLabel } from "./status";

describe("scheduler status helpers", () => {
  it("labels configured and missing scheduler state", () => {
    expect(schedulerStateLabel(true, true)).toBe("已配置");
    expect(schedulerStateLabel(false, true)).toBe("未登记任务");
    expect(schedulerStateLabel(false, false)).toBe("未初始化");
  });

  it("formats missing next run time", () => {
    expect(schedulerNextRunLabel(null)).toBe("等待调度器启动");
  });
});
