import { getJson } from "../../shared/api/client";
import type { StrategyRun, StrategyRunDetail } from "./model";

export function listRuns(strategyId?: string, limit = 30): Promise<StrategyRun[]> {
  const params = new URLSearchParams();
  if (strategyId) {
    params.set("strategy_id", strategyId);
  }
  params.set("limit", String(limit));
  return getJson<StrategyRun[]>(`/api/runs?${params.toString()}`);
}

export function getRunDetail(strategyId: string, tradeDate: string): Promise<StrategyRunDetail> {
  return getJson<StrategyRunDetail>(`/api/runs/${encodeURIComponent(strategyId)}/${encodeURIComponent(tradeDate)}`);
}
