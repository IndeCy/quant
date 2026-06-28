import { describe, expect, it } from "vitest";

import { validateSchedulerConfig } from "./config";

describe("validateSchedulerConfig", () => {
  it("accepts valid hour and minute", () => {
    expect(validateSchedulerConfig(16, 30)).toEqual({ valid: true, message: "调度时间有效" });
  });

  it("rejects invalid hour or minute", () => {
    expect(validateSchedulerConfig(24, 0)).toEqual({ valid: false, message: "小时必须在 0-23 之间" });
    expect(validateSchedulerConfig(16, 60)).toEqual({ valid: false, message: "分钟必须在 0-59 之间" });
  });
});
