import { useOutletContext } from "react-router-dom";

import type { DashboardContext } from "../../app/types";
import { ChartPanel } from "../../shared/ui/ChartPanel";
import { AllStrategyHoldingsPanel } from "./components/AllStrategyHoldingsPanel";
import { FactorCompositionPanel } from "./components/FactorCompositionPanel";
import { MetricGrid } from "./components/MetricGrid";
import { MultiStrategyChart } from "./components/MultiStrategyChart";
import { MarketBetaPanel } from "./components/MarketBetaPanel";
import { RecentReportsPanel } from "./components/RecentReportsPanel";
import { RecentRunsPanel } from "./components/RecentRunsPanel";
import { ReadinessPanel } from "./components/ReadinessPanel";
import { StrategyOverviewGrid } from "./components/StrategyOverviewGrid";
import { StrategyDefinitionPanel } from "./components/StrategyDefinitionPanel";
import { StrategyHoldingsPanel } from "./components/StrategyHoldingsPanel";
import { StrategyPerformanceChart } from "./components/StrategyPerformanceChart";

export function DashboardPage() {
  const data = useOutletContext<DashboardContext>();
  const selectedStrategy = data.selectedStrategyId === "ALL" ? data.strategy : data.strategyDetails[data.selectedStrategyId] ?? data.strategy;
  const selectedSeries = data.selectedStrategyId === "ALL" ? data.strategySeries : data.strategySeriesMap[selectedStrategy.strategy_id] ?? [];
  const selectedRuns =
    data.selectedStrategyId === "ALL" ? data.runs : data.runs.filter((run) => run.strategy_id === selectedStrategy.strategy_id);
  const selectedReports =
    data.selectedStrategyId === "ALL" ? data.reports : data.reports.filter((report) => report.strategy_id === selectedStrategy.strategy_id);
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
            <MultiStrategyChart
              strategies={data.strategies}
              seriesMap={data.strategySeriesMap}
              marketIndexComparison={data.marketIndexComparison}
            />
            <ChartPanel
              title="多策略回撤对比"
              dates={allDates}
              series={data.strategies.map((strategy) => {
                const byDate = new Map((data.strategySeriesMap[strategy.strategy_id] ?? []).map((item) => [item.trade_date, item.drawdown]));
                return { name: strategy.name, data: allDates.map((date) => byDate.get(date) ?? Number.NaN), valueType: "percent" as const };
              })}
            />
          </section>
          <aside className="column side">
            <MarketBetaPanel snapshot={data.marketBeta} marketSeries={data.marketSeries} />
            <ReadinessPanel report={data.readiness} />
            <RecentRunsPanel runs={data.runs} />
            <RecentReportsPanel reports={data.reports} />
          </aside>
        </div>
        <AllStrategyHoldingsPanel
          strategies={data.strategies}
          states={data.strategyInstanceStates}
          onSelect={data.selectStrategy}
        />
      </>
    );
  }
  return (
    <>
      <MetricGrid latest={selectedStrategy.latest_metrics} />
      <div className="content-grid">
        <section className="column wide">
          <StrategyPerformanceChart key={selectedStrategy.strategy_id} rows={selectedSeries} />
          <ChartPanel
            title="风险状态"
            dates={dates}
            series={[
              { name: "当前回撤", data: selectedSeries.map((item) => item.drawdown), valueType: "percent" },
              { name: "20日波动率", data: selectedSeries.map((item) => item.volatility_20), valueType: "percent" },
              { name: "目标仓位", data: selectedSeries.map((item) => item.exposure), yAxisIndex: 1, valueType: "percent" }
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
            scaleYAxis
          />
        </section>
        <aside className="column side">
          <MarketBetaPanel snapshot={data.marketBeta} marketSeries={data.marketSeries} />
          <ReadinessPanel report={data.readiness} />
          <StrategyDefinitionPanel strategy={selectedStrategy} />
          <StrategyHoldingsPanel
            name={selectedStrategy.name}
            state={data.strategyInstanceStates[selectedStrategy.strategy_id]}
          />
          <FactorCompositionPanel factors={selectedStrategy.factors ?? []} />
          <RecentRunsPanel runs={selectedRuns} />
          <RecentReportsPanel reports={selectedReports} />
        </aside>
      </div>
    </>
  );
}
