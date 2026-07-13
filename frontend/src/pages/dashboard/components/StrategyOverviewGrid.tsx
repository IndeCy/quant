import type { StrategyDefinition, StrategyMetric } from "../../../entities/strategy/model";
import { formatNumber, formatPercent } from "../../../shared/lib/formatters";

interface StrategyOverviewGridProps {
  strategies: StrategyDefinition[];
  seriesMap: Record<string, StrategyMetric[]>;
  onSelect: (strategyId: string) => void;
}

export function StrategyOverviewGrid({ strategies, seriesMap, onSelect }: StrategyOverviewGridProps) {
  return (
    <section className="strategy-overview-grid">
      {strategies.map((strategy) => {
        const latest = strategy.latest_metrics ?? seriesMap[strategy.strategy_id]?.at(-1);
        return (
          <button key={strategy.strategy_id} type="button" className="strategy-card" onClick={() => onSelect(strategy.strategy_id)}>
            <span className="card-kicker">{strategy.status}</span>
            <strong>{strategy.name}</strong>
            <div className="strategy-card-metrics">
              <span>{latest?.trade_date ?? "-"}</span>
              <span>{formatPercent(latest?.cumulative_return)}</span>
              <span>{formatPercent(latest?.drawdown)}</span>
              <span>{formatNumber(latest?.nav, 4)}</span>
            </div>
          </button>
        );
      })}
    </section>
  );
}
