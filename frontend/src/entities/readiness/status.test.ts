import { describe, expect, it } from "vitest";

import { readinessCheckLabel, readinessTone, readinessTitle } from "./status";

describe("readiness status helpers", () => {
  it("maps overall readiness to local dashboard labels", () => {
    expect(readinessTitle("READY")).toBe("可连续运行");
    expect(readinessTone("READY")).toBe("success");
    expect(readinessTitle("NOT_READY")).toBe("需要处理");
    expect(readinessTone("NOT_READY")).toBe("danger");
  });

  it("maps live readiness checks to Chinese labels", () => {
    expect(readinessCheckLabel("backup_manifest")).toBe("备份清单");
    expect(readinessCheckLabel("notification_channel")).toBe("Bark 通知");
    expect(readinessCheckLabel("manual_order_workflow")).toBe("手工调仓闭环");
    expect(readinessCheckLabel("broker_permission_boundary")).toBe("券商权限边界");
  });
});
