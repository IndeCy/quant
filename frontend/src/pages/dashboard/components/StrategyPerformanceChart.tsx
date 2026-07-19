import { useMemo, useState } from "react";

import type { StrategyMetric } from "../../../entities/strategy/model";
import { buildPaperWindow } from "../../../entities/strategy/paperWindow";
import { ChartPanel } from "../../../shared/ui/ChartPanel";
import { PerformanceModeSwitch, type PerformanceMode } from "./PerformanceModeSwitch";

interface StrategyPerformanceChartProps {
  rows: StrategyMetric[];
}

export function StrategyPerformanceChart({ rows }: StrategyPerformanceChartProps) {
  const paperWindow = useMemo(() => buildPaperWindow(rows), [rows]);
  const [mode, setMode] = useState<PerformanceMode>(paperWindow.dates.length > 0 ? "paper" : "history");
  const historySeries = [
    { name: "策略净值", data: rows.map((item) => item.nav) },
    { name: "基准", data: rows.map((item) => item.benchmark_nav) },
    { name: "超额收益", data: rows.map((item) => item.excess_return), yAxisIndex: 1, valueType: "percent" as const }
  ];
  const paperSeries = [
    { name: "Paper实际", data: paperWindow.paperNav },
    { name: "回测同期", data: paperWindow.theoreticalNav },
    { name: "基准同期", data: paperWindow.benchmarkNav }
  ];

  return (
    <>
      <PerformanceModeSwitch mode={mode} onChange={setMode} paperDates={paperWindow.dates} />
      <ChartPanel
        title={mode === "paper" ? "Paper模拟与同期表现" : "策略收益与基准"}
        dates={mode === "paper" ? paperWindow.dates : rows.map((item) => item.trade_date)}
        series={mode === "paper" ? paperSeries : historySeries}
        dualAxis={mode === "history"}
        scaleYAxis
      />
    </>
  );
}
