import type { ReadinessReport } from "../entities/readiness/model";
import type { SchedulerStatus } from "../entities/scheduler/model";
import type { StrategyDefinition } from "../entities/strategy/model";
import type { DashboardData } from "./types";

export function chooseDefaultStrategyId(strategies: Array<Partial<StrategyDefinition>>): string {
  const active = strategies.find((item) => item.status === "active");
  if (active?.strategy_id) {
    return active.strategy_id;
  }
  const withMetrics = strategies.find((item) => item.latest_metrics);
  return withMetrics?.strategy_id ?? strategies[0]?.strategy_id ?? "";
}

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
