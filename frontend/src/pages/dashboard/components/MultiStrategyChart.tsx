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
    .flatMap((strategy) => {
      const rows = seriesMap[strategy.strategy_id] ?? [];
      const navByDate = new Map(rows.map((item) => [item.trade_date, item.nav]));
      const paperByDate = new Map(rows.map((item) => [item.trade_date, item.paper_nav ?? Number.NaN]));
      return [
        {
          name: strategy.name,
          data: dates.map((date) => navByDate.get(date) ?? Number.NaN)
        },
        {
          name: `${strategy.name} Paper`,
          data: dates.map((date) => paperByDate.get(date) ?? Number.NaN)
        }
      ];
    })
    .filter((item) => item.data.some((value) => Number.isFinite(value)));
  return <ChartPanel title="多策略净值对比" dates={dates} series={series} />;
}
