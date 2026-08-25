import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import {
  buildChartRangeLabel,
  calculateZoomStart,
  formatChartAxisValue,
  formatChartValue,
  normalizeChartData,
  resolveSeriesColor,
  type ChartValueType
} from "./chartTheme";

echarts.use([LineChart, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

interface SeriesLine {
  name: string;
  data: Array<number | null>;
  yAxisIndex?: number;
  valueType?: ChartValueType;
}

interface ChartPanelProps {
  title: string;
  dates: string[];
  series: SeriesLine[];
  dualAxis?: boolean;
  scaleYAxis?: boolean;
}

export function ChartPanel({ title, dates, series, dualAxis = false, scaleYAxis = false }: ChartPanelProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const showZoom = dates.length > 30;

  useEffect(() => {
    if (!ref.current) {
      return;
    }
    const chart = echarts.init(ref.current);
    const zoomStart = calculateZoomStart(dates.length);
    const axisValueType = (axisIndex: number) =>
      series.find((item) => (item.yAxisIndex ?? 0) === axisIndex)?.valueType ?? "number";
    const yAxis = (axisIndex: number, position: "left" | "right") => ({
      type: "value",
      position,
      scale: scaleYAxis,
      axisLabel: { color: "#64748b", formatter: (value: number) => formatChartAxisValue(value, axisValueType(axisIndex)) },
      axisLine: { show: axisIndex === 1, lineStyle: { color: "#cbd5e1" } },
      splitLine: { show: axisIndex === 0, lineStyle: { color: "#eef2f7" } }
    });
    chart.setOption({
      animation: false,
      tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
      legend: { type: "scroll", top: 0, left: 0, right: 0, textStyle: { color: "#475569" } },
      grid: { left: 58, right: dualAxis ? 58 : 20, top: 40, bottom: showZoom ? 64 : 34 },
      xAxis: {
        type: "category",
        data: dates,
        boundaryGap: false,
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#cbd5e1" } },
        axisLabel: { color: "#64748b", hideOverlap: true }
      },
      yAxis: dualAxis ? [yAxis(0, "left"), yAxis(1, "right")] : [yAxis(0, "left")],
      dataZoom: showZoom
        ? [
            { type: "inside", start: zoomStart, end: 100 },
            { type: "slider", start: zoomStart, end: 100, height: 18, bottom: 8 }
          ]
        : [],
      series: series.map((item, index) => ({
        name: item.name,
        type: "line",
        showSymbol: dates.length <= 30,
        symbolSize: 6,
        smooth: false,
        connectNulls: false,
        yAxisIndex: item.yAxisIndex ?? 0,
        data: normalizeChartData(item.data),
        lineStyle: { width: 1.8, color: resolveSeriesColor(item.name, index) },
        itemStyle: { color: resolveSeriesColor(item.name, index) },
        emphasis: { focus: "series" },
        tooltip: { valueFormatter: (value: number) => formatChartValue(Number(value), item.valueType) }
      }))
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [dates, dualAxis, scaleYAxis, series, showZoom]);

  return (
    <section className="panel chart-panel">
      <div className="panel-head chart-panel-head">
        <h2>{title}</h2>
        <span>{buildChartRangeLabel(dates)}</span>
      </div>
      <div ref={ref} className="chart terminal-chart" />
    </section>
  );
}
