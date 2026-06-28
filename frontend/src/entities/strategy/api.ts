import { getJson } from "../../shared/api/client";
import type { StrategyDefinition, StrategyMetric } from "./model";

export function listStrategies(): Promise<StrategyDefinition[]> {
  return getJson<StrategyDefinition[]>("/api/strategies");
}

export function getStrategy(strategyId: string): Promise<StrategyDefinition> {
  return getJson<StrategyDefinition>(`/api/strategies/${strategyId}`);
}

export function getStrategySeries(strategyId: string): Promise<StrategyMetric[]> {
  return getJson<StrategyMetric[]>(`/api/series/strategy/${strategyId}`);
}
