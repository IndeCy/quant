import { useOutletContext } from "react-router-dom";

import type { DashboardData } from "../../app/types";
import { formatPercent } from "../../shared/lib/formatters";
import { ChartPanel } from "../../shared/ui/ChartPanel";
import { PageHeader } from "../../shared/ui/PageHeader";

export function RiskPage() {
  const data = useOutletContext<DashboardData>();
  return (
    <>
      <PageHeader title="风险" description="观察风险层、回撤、波动率和仓位变化。" />
      <ChartPanel
        title="风险层指标"
        dates={data.strategySeries.map((item) => item.trade_date)}
        series={[
          { name: "当前回撤", data: data.strategySeries.map((item) => item.drawdown) },
          { name: "20日波动率", data: data.strategySeries.map((item) => item.volatility_20) },
          { name: "仓位", data: data.strategySeries.map((item) => item.exposure), yAxisIndex: 1 }
        ]}
        dualAxis
      />
      <section className="panel compact">
        <dl>
          <div>
            <dt>当前回撤</dt>
            <dd>{formatPercent(data.strategy.latest_metrics?.drawdown)}</dd>
          </div>
          <div>
            <dt>最大回撤</dt>
            <dd>{formatPercent(data.strategy.latest_metrics?.max_drawdown)}</dd>
          </div>
          <div>
            <dt>20日波动率</dt>
            <dd>{formatPercent(data.strategy.latest_metrics?.volatility_20)}</dd>
          </div>
        </dl>
      </section>
    </>
  );
}
