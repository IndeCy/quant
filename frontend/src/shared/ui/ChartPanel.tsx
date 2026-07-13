import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TitleComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([LineChart, GridComponent, LegendComponent, TitleComponent, TooltipComponent, CanvasRenderer]);

interface SeriesLine {
  name: string;
  data: number[];
  yAxisIndex?: number;
}

interface ChartPanelProps {
  title: string;
  dates: string[];
  series: SeriesLine[];
  dualAxis?: boolean;
}

export function ChartPanel({ title, dates, series, dualAxis = false }: ChartPanelProps) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ref.current) {
      return;
    }
    const chart = echarts.init(ref.current);
    chart.setOption({
      title: { text: title, left: 0, top: 0, textStyle: { fontSize: 14, fontWeight: 700 } },
      tooltip: { trigger: "axis" },
      legend: { top: 0, right: 0 },
      grid: { left: 48, right: dualAxis ? 48 : 18, top: 48, bottom: 32 },
      xAxis: { type: "category", data: dates, axisTick: { show: false } },
      yAxis: dualAxis ? [{ type: "value" }, { type: "value", position: "right" }] : [{ type: "value" }],
      series: series.map((item) => ({
        name: item.name,
        type: "line",
        showSymbol: false,
        smooth: false,
        yAxisIndex: item.yAxisIndex ?? 0,
        data: item.data
      }))
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [dates, dualAxis, series, title]);

  return (
    <section className="panel">
      <div ref={ref} className="chart" />
    </section>
  );
}
