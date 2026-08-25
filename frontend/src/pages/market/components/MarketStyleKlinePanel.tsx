import { useEffect, useRef } from "react";
import { CandlestickChart, LineChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

import type { MarketStyleSeries } from "../../../entities/market/model";
import { trendStyleDisplay } from "../../../entities/market/styleDisplay";
import { formatNumber, formatPercent } from "../../../shared/lib/formatters";
import { CHART_COLORS, calculateZoomStart } from "../../../shared/ui/chartTheme";

echarts.use([CandlestickChart, LineChart, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

interface MarketStyleKlinePanelProps {
  series: MarketStyleSeries;
}

export function MarketStyleKlinePanel({ series }: MarketStyleKlinePanelProps) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const trend = trendStyleDisplay(series.summary.trend_state);

  useEffect(() => {
    if (!chartRef.current) return;
    const chart = echarts.init(chartRef.current);
    const dates = series.bars.map((item) => item.trade_date);
    const zoomStart = calculateZoomStart(dates.length);
    chart.setOption({
      animation: false,
      tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
      legend: { top: 0, right: 0, data: ["日K", "MA5", "MA10", "MA20", "MA60"] },
      grid: { left: 54, right: 18, top: 42, bottom: 64 },
      xAxis: {
        type: "category",
        data: dates,
        boundaryGap: true,
        axisLine: { lineStyle: { color: "#cbd5e1" } },
        axisLabel: { color: "#64748b", hideOverlap: true }
      },
      yAxis: {
        type: "value",
        scale: true,
        splitLine: { lineStyle: { color: "#eef2f7" } }
      },
      dataZoom: [
        { type: "inside", start: zoomStart, end: 100 },
        { type: "slider", start: zoomStart, end: 100, height: 18, bottom: 8 }
      ],
      series: [
        {
          name: "日K",
          type: "candlestick",
          data: series.bars.map((item) => [item.open, item.close, item.low, item.high]),
          itemStyle: {
            color: CHART_COLORS.red,
            color0: CHART_COLORS.green,
            borderColor: CHART_COLORS.red,
            borderColor0: CHART_COLORS.green
          }
        },
        ...[
          ["MA5", "ma5", CHART_COLORS.blue],
          ["MA10", "ma10", CHART_COLORS.amber],
          ["MA20", "ma20", CHART_COLORS.red],
          ["MA60", "ma60", CHART_COLORS.green]
        ].map(([name, field, color]) => ({
          name,
          type: "line",
          data: series.bars.map((item) => item[field as "ma5" | "ma10" | "ma20" | "ma60"]),
          showSymbol: false,
          connectNulls: false,
          lineStyle: { width: 1.4, color },
          itemStyle: { color }
        }))
      ]
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [series]);

  return (
    <section className="panel market-style-chart-panel">
      <div className="panel-head market-style-chart-head">
        <div>
          <h2>{series.name}</h2>
          <p>{series.proxy_name} · {series.symbol}</p>
        </div>
        <span className={`status ${trend.tone}`}>{trend.label}</span>
      </div>
      <div className="market-style-inline-metrics">
        <span>点位 <strong>{formatNumber(series.summary.close, 2)}</strong></span>
        <span>20日 <strong>{formatPercent(series.summary.return_20, 2)}</strong></span>
        <span>距MA20 <strong>{formatPercent(series.summary.distance_ma20, 2)}</strong></span>
        <span>距MA60 <strong>{formatPercent(series.summary.distance_ma60, 2)}</strong></span>
      </div>
      <div ref={chartRef} className="market-style-kline" />
    </section>
  );
}
