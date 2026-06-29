import { useOutletContext } from "react-router-dom";

import type { DashboardData } from "../../app/types";
import { ChartPanel } from "../../shared/ui/ChartPanel";
import { FactorCompositionPanel } from "./components/FactorCompositionPanel";
import { MetricGrid } from "./components/MetricGrid";
import { RecentReportsPanel } from "./components/RecentReportsPanel";
import { RecentRunsPanel } from "./components/RecentRunsPanel";
import { ReadinessPanel } from "./components/ReadinessPanel";
import { StrategyDefinitionPanel } from "./components/StrategyDefinitionPanel";

export function DashboardPage() {
  const data = useOutletContext<DashboardData>();
  const dates = data.strategySeries.map((item) => item.trade_date);
  return (
    <>
      <MetricGrid latest={data.strategy.latest_metrics} />
      <div className="content-grid">
        <section className="column wide">
          <ChartPanel
            title="策略收益与基准"
            dates={dates}
            series={[
              { name: "策略净值", data: data.strategySeries.map((item) => item.nav) },
              { name: "510300", data: data.strategySeries.map((item) => item.benchmark_nav) },
              { name: "超额收益", data: data.strategySeries.map((item) => item.excess_return), yAxisIndex: 1 }
            ]}
            dualAxis
          />
          <ChartPanel
            title="风险状态"
            dates={dates}
            series={[
              { name: "当前回撤", data: data.strategySeries.map((item) => item.drawdown) },
              { name: "20日波动率", data: data.strategySeries.map((item) => item.volatility_20) },
              { name: "目标仓位", data: data.strategySeries.map((item) => item.exposure), yAxisIndex: 1 }
            ]}
            dualAxis
          />
          <ChartPanel
            title="大盘模块"
            dates={data.marketSeries.map((item) => item.trade_date)}
            series={[
              { name: "510300净值", data: data.marketSeries.map((item) => item.benchmark_nav) },
              { name: "MA60", data: data.marketSeries.map((item) => item.ma60) },
              { name: "MA120", data: data.marketSeries.map((item) => item.ma120) }
            ]}
          />
        </section>
        <aside className="column side">
          <ReadinessPanel report={data.readiness} />
          <StrategyDefinitionPanel strategy={data.strategy} />
          <FactorCompositionPanel factors={data.strategy.factors ?? []} />
          <RecentRunsPanel runs={data.runs} />
          <RecentReportsPanel reports={data.reports} />
        </aside>
      </div>
    </>
  );
}
