import { useOutletContext } from "react-router-dom";

import type { DashboardContext } from "../../app/types";
import { formatPercent } from "../../shared/lib/formatters";
import { ChartPanel } from "../../shared/ui/ChartPanel";
import { PageHeader } from "../../shared/ui/PageHeader";

export function RiskPage() {
  const data = useOutletContext<DashboardContext>();
  const selectedStrategy = data.selectedStrategyId === "ALL" ? data.strategy : data.strategyDetails[data.selectedStrategyId] ?? data.strategy;
  const selectedSeries = data.selectedStrategyId === "ALL" ? data.strategySeries : data.strategySeriesMap[selectedStrategy.strategy_id] ?? [];
  return (
    <>
      <PageHeader title="风险" description="观察风险层、回撤、波动率和仓位变化。" />
      <ChartPanel
        title={`${selectedStrategy.name} 风险层指标`}
        dates={selectedSeries.map((item) => item.trade_date)}
        series={[
          { name: "当前回撤", data: selectedSeries.map((item) => item.drawdown), valueType: "percent" },
          { name: "20日波动率", data: selectedSeries.map((item) => item.volatility_20), valueType: "percent" },
          { name: "仓位", data: selectedSeries.map((item) => item.exposure), yAxisIndex: 1, valueType: "percent" }
        ]}
        dualAxis
      />
      <section className="panel compact">
        <dl>
          <div>
            <dt>当前回撤</dt>
            <dd>{formatPercent(selectedStrategy.latest_metrics?.drawdown)}</dd>
          </div>
          <div>
            <dt>最大回撤</dt>
            <dd>{formatPercent(selectedStrategy.latest_metrics?.max_drawdown)}</dd>
          </div>
          <div>
            <dt>20日波动率</dt>
            <dd>{formatPercent(selectedStrategy.latest_metrics?.volatility_20)}</dd>
          </div>
        </dl>
      </section>
    </>
  );
}
