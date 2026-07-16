export type PerformanceMode = "history" | "paper";

interface PerformanceModeSwitchProps {
  mode: PerformanceMode;
  onChange: (mode: PerformanceMode) => void;
  paperDates: string[];
}

export function PerformanceModeSwitch({ mode, onChange, paperDates }: PerformanceModeSwitchProps) {
  const hasPaper = paperDates.length > 0;
  const paperRange = hasPaper ? `${paperDates[0]} - ${paperDates[paperDates.length - 1]}` : "暂无数据";
  return (
    <div className="chart-mode-bar">
      <div className="segmented-control" role="group" aria-label="净值观察区间">
        <button type="button" className={mode === "history" ? "active" : ""} onClick={() => onChange("history")}>
          历史回测
        </button>
        <button
          type="button"
          className={mode === "paper" ? "active" : ""}
          disabled={!hasPaper}
          onClick={() => onChange("paper")}
        >
          Paper观察
        </button>
      </div>
      <span className="chart-mode-meta">{mode === "paper" ? `${paperDates.length}个交易日 · ${paperRange}` : "完整历史"}</span>
    </div>
  );
}
