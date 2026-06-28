import type { StrategyMetric } from "../../../entities/strategy/model";
import { formatNumber, formatPercent } from "../../../shared/lib/formatters";
import { MetricCard } from "../../../shared/ui/MetricCard";

interface MetricGridProps {
  latest?: StrategyMetric | null;
}

export function MetricGrid({ latest }: MetricGridProps) {
  return (
    <section className="metrics">
      <MetricCard label="数据日期" value={latest?.trade_date ?? "-"} />
      <MetricCard label="策略净值" value={formatNumber(latest?.nav, 4)} />
      <MetricCard label="累计收益" value={formatPercent(latest?.cumulative_return)} />
      <MetricCard label="超额收益" value={formatPercent(latest?.excess_return)} />
      <MetricCard label="当前回撤" value={formatPercent(latest?.drawdown)} />
      <MetricCard label="20日波动率" value={formatPercent(latest?.volatility_20)} />
      <MetricCard label="当前仓位" value={formatPercent(latest?.exposure)} />
      <MetricCard label="失败委托" value={String(latest?.failed_order_count ?? 0)} />
    </section>
  );
}
