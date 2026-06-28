import type { FactorDefinition } from "../entities/factor/model";
import type { MarketMetric } from "../entities/market/model";
import type { ReportIndex } from "../entities/report/model";
import type { StrategyRun } from "../entities/run/model";
import type { StrategyDefinition, StrategyMetric } from "../entities/strategy/model";

export interface DashboardData {
  strategies: StrategyDefinition[];
  strategy: StrategyDefinition;
  factors: FactorDefinition[];
  reports: ReportIndex[];
  runs: StrategyRun[];
  strategySeries: StrategyMetric[];
  marketSeries: MarketMetric[];
}
