import { useOutletContext } from "react-router-dom";

import type { DashboardContext } from "../../app/types";
import { ChartPanel } from "../../shared/ui/ChartPanel";
import { FactorCompositionPanel } from "./components/FactorCompositionPanel";
import { MetricGrid } from "./components/MetricGrid";
import { MultiStrategyChart } from "./components/MultiStrategyChart";
import { RecentReportsPanel } from "./components/RecentReportsPanel";
import { RecentRunsPanel } from "./components/RecentRunsPanel";
import { ReadinessPanel } from "./components/ReadinessPanel";
import { StrategyOverviewGrid } from "./components/StrategyOverviewGrid";
import { StrategyDefinitionPanel } from "./components/StrategyDefinitionPanel";

export function DashboardPage() {
  const data = useOutletContext<DashboardContext>();
  const selectedStrategy = data.selectedStrategyId === "ALL" ? data.strategy : data.strategyDetails[data.selectedStrategyId] ?? data.strategy;
  const selectedSeries = data.selectedStrategyId === "ALL" ? data.strategySeries : data.strategySeriesMap[selectedStrategy.strategy_id] ?? [];
  const dates = selectedSeries.map((item) => item.trade_date);
  const allDates = Array.from(
    new Set(data.strategies.flatMap((strategy) => data.strategySeriesMap[strategy.strategy_id]?.map((item) => item.trade_date) ?? []))
  ).sort();
  if (data.selectedStrategyId === "ALL") {
    return (
      <>
        <StrategyOverviewGrid strategies={data.strategies} seriesMap={data.strategySeriesMap} onSelect={data.selectStrategy} />
        <div className="content-grid">
          <section className="column wide">
            <MultiStrategyChart strategies={data.strategies} seriesMap={data.strategySeriesMap} />
            <ChartPanel
              title="多策略回撤对比"
              dates={allDates}
              series={data.strategies.map((strategy) => {
                const byDate = new Map((data.strategySeriesMap[strategy.strategy_id] ?? []).map((item) => [item.trade_date, item.drawdown]));
                return { name: strategy.name, data: allDates.map((date) => byDate.get(date) ?? Number.NaN) };
              })}
            />
          </section>
          <aside className="column side">
            <ReadinessPanel report={data.readiness} />
            <RecentRunsPanel runs={data.runs} />
            <RecentReportsPanel reports={data.reports} />
          </aside>
        </div>
      </>
    );
  }
  return (
    <>
      <MetricGrid latest={selectedStrategy.latest_metrics} />
      <div className="content-grid">
        <section className="column wide">
          <ChartPanel
            title="策略收益与基准"
            dates={dates}
            series={[
              { name: "策略净值", data: selectedSeries.map((item) => item.nav) },
              { name: "基准", data: selectedSeries.map((item) => item.benchmark_nav) },
              { name: "超额收益", data: selectedSeries.map((item) => item.excess_return), yAxisIndex: 1 }
            ]}
            dualAxis
          />
          <ChartPanel
            title="风险状态"
            dates={dates}
            series={[
              { name: "当前回撤", data: selectedSeries.map((item) => item.drawdown) },
              { name: "20日波动率", data: selectedSeries.map((item) => item.volatility_20) },
              { name: "目标仓位", data: selectedSeries.map((item) => item.exposure), yAxisIndex: 1 }
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
          <StrategyDefinitionPanel strategy={selectedStrategy} />
          <FactorCompositionPanel factors={selectedStrategy.factors ?? []} />
          <RecentRunsPanel runs={data.runs} />
          <RecentReportsPanel reports={data.reports} />
        </aside>
      </div>
    </>
  );
}
