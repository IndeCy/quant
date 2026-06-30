import type { StrategyDefinition, StrategyMetric } from "../../../entities/strategy/model";
import { ChartPanel } from "../../../shared/ui/ChartPanel";

interface MultiStrategyChartProps {
  strategies: StrategyDefinition[];
  seriesMap: Record<string, StrategyMetric[]>;
}

export function MultiStrategyChart({ strategies, seriesMap }: MultiStrategyChartProps) {
  const dates = Array.from(
    new Set(strategies.flatMap((strategy) => seriesMap[strategy.strategy_id]?.map((item) => item.trade_date) ?? []))
  ).sort();
  const series = strategies
    .map((strategy) => {
      const byDate = new Map((seriesMap[strategy.strategy_id] ?? []).map((item) => [item.trade_date, item.nav]));
      return {
        name: strategy.name,
        data: dates.map((date) => byDate.get(date) ?? Number.NaN)
      };
    })
    .filter((item) => item.data.some((value) => Number.isFinite(value)));
  return <ChartPanel title="多策略净值对比" dates={dates} series={series} />;
}
