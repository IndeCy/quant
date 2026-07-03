import { getJson, postJson } from "../../shared/api/client";
import type {
  StrategyDefinition,
  StrategyInstance,
  StrategyInstanceState,
  StrategyMetric,
  StrategyTemplate,
  StrategyTransitionPayload
} from "./model";

export function listStrategies(): Promise<StrategyDefinition[]> {
  return getJson<StrategyDefinition[]>("/api/strategies");
}

export function getStrategy(strategyId: string): Promise<StrategyDefinition> {
  return getJson<StrategyDefinition>(`/api/strategies/${strategyId}`);
}

export function getStrategySeries(strategyId: string): Promise<StrategyMetric[]> {
  return getJson<StrategyMetric[]>(`/api/series/strategy/${strategyId}`);
}

export function listStrategyTemplates(): Promise<StrategyTemplate[]> {
  return getJson<StrategyTemplate[]>("/api/strategy-templates");
}

export function listStrategyInstances(enabledOnly = false): Promise<StrategyInstance[]> {
  const suffix = enabledOnly ? "?enabled_only=true" : "";
  return getJson<StrategyInstance[]>(`/api/strategy-instances${suffix}`);
}

export function saveStrategyInstance(payload: StrategyInstance): Promise<StrategyInstance> {
  return postJson<StrategyInstance>("/api/strategy-instances", payload);
}

export function getStrategyInstanceState(strategyId: string): Promise<StrategyInstanceState> {
  return getJson<StrategyInstanceState>(`/api/strategy-instances/${strategyId}/state`);
}

export function transitionStrategyInstance(strategyId: string, payload: StrategyTransitionPayload): Promise<StrategyInstance> {
  return postJson<StrategyInstance>(`/api/strategy-instances/${strategyId}/transition`, payload);
}
