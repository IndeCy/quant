import type { ReadinessReport } from "../entities/readiness/model";
import type { SchedulerStatus } from "../entities/scheduler/model";
import type { DashboardData } from "./types";

export function mergeRuntimeStatus(
  data: DashboardData,
  schedulerStatus: SchedulerStatus,
  readiness: ReadinessReport
): DashboardData {
  return {
    ...data,
    schedulerStatus,
    readiness
  };
}
