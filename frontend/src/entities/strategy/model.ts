import type { FactorDefinition } from "../factor/model";
import type { StrategyRun } from "../run/model";

export interface StrategyDefinition {
  strategy_id: string;
  name: string;
  status: string;
  strategy_type: string;
  description: string;
  config: Record<string, string | number | boolean>;
  factors?: FactorDefinition[];
  latest_run?: StrategyRun | null;
  latest_metrics?: StrategyMetric | null;
}

export interface StrategyMetric {
  trade_date: string;
  strategy_id: string;
  nav: number;
  daily_return: number;
  cumulative_return: number;
  benchmark_id: string;
  benchmark_nav: number;
  benchmark_return: number;
  excess_return: number;
  drawdown: number;
  max_drawdown: number;
  volatility_20: number;
  volatility_60: number;
  sharpe_rolling: number;
  exposure: number;
  total_execution_cost: number;
  failed_order_count: number;
}
