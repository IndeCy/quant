import type { StrategyDefinition, StrategyInstanceState } from "../../../entities/strategy/model";
import { formatPercent } from "../../../shared/lib/formatters";

interface AllStrategyHoldingsPanelProps {
  strategies: StrategyDefinition[];
  states: Record<string, StrategyInstanceState>;
  onSelect: (strategyId: string) => void;
}

export function AllStrategyHoldingsPanel({ strategies, states, onSelect }: AllStrategyHoldingsPanelProps) {
  const visibleStrategies = strategies.filter((strategy) => states[strategy.strategy_id]);
  return (
    <section className="panel all-strategy-holdings-panel">
      <div className="panel-head">
        <div>
          <h2>策略最新持仓</h2>
          <p>目标持仓来自最近一次策略状态；点击策略名称可进入单策略详情。</p>
        </div>
        <span className="status neutral">{visibleStrategies.length}个策略</span>
      </div>
      <div className="all-strategy-holdings-grid">
        {visibleStrategies.map((strategy) => {
          const state = states[strategy.strategy_id];
          const holdings = [...(state?.holdings ?? [])].sort((left, right) => right.weight - left.weight);
          return (
            <article key={strategy.strategy_id} className="all-strategy-holdings-card">
              <button type="button" onClick={() => onSelect(strategy.strategy_id)}>
                <strong>{strategy.name}</strong>
                <span>{state?.trade_date ?? "尚未生成"}</span>
              </button>
              <div className="holdings-card-meta">
                <span>{holdings.length}只</span>
                <span>{formatPercent(holdings.reduce((total, holding) => total + holding.weight, 0))}</span>
              </div>
              {holdings.length === 0 ? (
                <p className="muted-text">暂无有效目标持仓</p>
              ) : (
                <div className="holdings-chip-list">
                  {holdings.map((holding) => (
                    <span key={holding.symbol}>
                      {holding.symbol}
                      <strong>{formatPercent(holding.weight)}</strong>
                    </span>
                  ))}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
