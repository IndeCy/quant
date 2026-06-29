import { describe, expect, it } from "vitest";

import type { ReadinessReport } from "../entities/readiness/model";
import type { SchedulerStatus } from "../entities/scheduler/model";
import type { DashboardData } from "./types";
import { mergeRuntimeStatus } from "./state";

describe("mergeRuntimeStatus", () => {
  it("updates scheduler and readiness without mutating the previous dashboard data", () => {
    const previous = {
      schedulerStatus: { enabled: false },
      readiness: { status: "NOT_READY", checks: [] },
      strategy: { strategy_id: "quality_overlay" }
    } as unknown as DashboardData;
    const schedulerStatus: SchedulerStatus = {
      enabled: true,
      job_id: "quality_overlay_daily_pipeline",
      job_store_path: "/tmp/scheduler.sqlite",
      job_store_exists: true,
      next_run_time: "2026-06-30T16:30:00+08:00",
      schedule: "mon-fri 16:30 Asia/Shanghai",
      start_command: "python scripts/run_local_scheduler.py",
      log_path: "/tmp/scheduler.log"
    };
    const readiness: ReadinessReport = {
      status: "READY",
      checks: [{ name: "scheduler_job", status: "PASS", message: "已登记" }]
    };

    const next = mergeRuntimeStatus(previous, schedulerStatus, readiness);

    expect(next).not.toBe(previous);
    expect(next.schedulerStatus.enabled).toBe(true);
    expect(next.readiness.status).toBe("READY");
    expect(previous.schedulerStatus.enabled).toBe(false);
  });
});
