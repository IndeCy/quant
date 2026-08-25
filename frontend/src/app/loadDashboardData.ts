import type { MarketBetaSnapshot, MarketIndexComparison, MarketMetric } from "../entities/market/model";
import { getReadinessReport } from "../entities/readiness/api";
import type { ReadinessReport } from "../entities/readiness/model";
import type { ReportIndex } from "../entities/report/model";
import type { StrategyRun } from "../entities/run/model";
import type { StrategyDefinition, StrategyInstanceState, StrategyMetric } from "../entities/strategy/model";
import { getJson } from "../shared/api/client";
import { chooseDefaultStrategyId } from "./state";
import type { DashboardBootstrapData } from "./types";

interface DashboardBootstrapPayload {
  strategies: StrategyDefinition[];
  strategy_details: Record<string, StrategyDefinition>;
  strategy_series_map: Record<string, StrategyMetric[]>;
  strategy_instance_states: Record<string, StrategyInstanceState>;
  market_index_comparison: MarketIndexComparison;
  market_series: MarketMetric[];
  market_beta: MarketBetaSnapshot;
  readiness: ReadinessReport;
  runs: StrategyRun[];
  reports: ReportIndex[];
}

export async function loadDashboardData(): Promise<DashboardBootstrapData> {
  const [payload, readiness] = await Promise.all([
    getJson<DashboardBootstrapPayload>("/api/dashboard/bootstrap"),
    getReadinessReport()
  ]);
  const strategyId = chooseDefaultStrategyId(Object.values(payload.strategy_details));
  const strategy = payload.strategy_details[strategyId] ?? payload.strategies[0];
  return {
    strategies: payload.strategies,
    strategy,
    reports: payload.reports,
    runs: payload.runs,
    strategySeries: payload.strategy_series_map[strategy.strategy_id] ?? [],
    strategyDetails: payload.strategy_details,
    strategySeriesMap: payload.strategy_series_map,
    strategyInstanceStates: payload.strategy_instance_states,
    marketIndexComparison: payload.market_index_comparison,
    marketSeries: payload.market_series,
    marketBeta: payload.market_beta,
    readiness
  };
}
