import { useMemo, useState } from "react";

import type { StrategyDefinition, StrategyMetric } from "../../../entities/strategy/model";
import { buildPaperWindow } from "../../../entities/strategy/paperWindow";
import { ChartPanel } from "../../../shared/ui/ChartPanel";
import { PerformanceModeSwitch, type PerformanceMode } from "./PerformanceModeSwitch";

interface MultiStrategyChartProps {
  strategies: StrategyDefinition[];
  seriesMap: Record<string, StrategyMetric[]>;
}

export function MultiStrategyChart({ strategies, seriesMap }: MultiStrategyChartProps) {
  const historyDates = Array.from(
    new Set(strategies.flatMap((strategy) => seriesMap[strategy.strategy_id]?.map((item) => item.trade_date) ?? []))
  ).sort();
  const paperWindows = useMemo(
    () => Object.fromEntries(strategies.map((strategy) => [strategy.strategy_id, buildPaperWindow(seriesMap[strategy.strategy_id] ?? [])])),
    [seriesMap, strategies]
  );
  const paperDates = Array.from(new Set(strategies.flatMap((strategy) => paperWindows[strategy.strategy_id]?.dates ?? []))).sort();
  const [mode, setMode] = useState<PerformanceMode>(paperDates.length > 0 ? "paper" : "history");
  const historySeries = strategies.map((strategy) => {
    const rows = seriesMap[strategy.strategy_id] ?? [];
    const navByDate = new Map(rows.map((item) => [item.trade_date, item.nav]));
    return { name: strategy.name, data: historyDates.map((date) => navByDate.get(date) ?? Number.NaN) };
  });
  const paperSeries = strategies
    .map((strategy) => {
      const paperWindow = paperWindows[strategy.strategy_id];
      const paperByDate = new Map(paperWindow.dates.map((date, index) => [date, paperWindow.paperNav[index]]));
      return { name: `${strategy.name} Paper`, data: paperDates.map((date) => paperByDate.get(date) ?? Number.NaN) };
    })
    .filter((item) => item.data.some((value) => Number.isFinite(value)));
  return (
    <>
      <PerformanceModeSwitch mode={mode} onChange={setMode} paperDates={paperDates} />
      <ChartPanel
        title={mode === "paper" ? "多策略Paper净值对比" : "多策略历史净值对比"}
        dates={mode === "paper" ? paperDates : historyDates}
        series={mode === "paper" ? paperSeries : historySeries}
        scaleYAxis
      />
    </>
  );
}
