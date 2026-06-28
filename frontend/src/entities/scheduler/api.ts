import { getJson, postJson } from "../../shared/api/client";
import type { SchedulerConfigPayload, SchedulerStatus } from "./model";

export function getSchedulerStatus(): Promise<SchedulerStatus> {
  return getJson<SchedulerStatus>("/api/scheduler/status");
}

export function configureSchedulerJob(payload: SchedulerConfigPayload): Promise<SchedulerStatus> {
  return postJson<SchedulerStatus>("/api/scheduler/daily-job", payload);
}
