import type { DashboardContext } from "../types";
import { riskTone } from "../../shared/lib/formatters";

interface TopStatusBarProps {
  data: DashboardContext;
}

export function TopStatusBar({ data }: TopStatusBarProps) {
  const strategy = data.selectedStrategyId === "ALL" ? null : data.strategyDetails[data.selectedStrategyId];
  const status = strategy?.latest_run?.status ?? strategy?.status ?? "UNKNOWN";
  const tradeDate = strategy?.latest_metrics?.trade_date ?? "-";
  return (
    <header className="top-status">
      <div>
        <p className="eyebrow">Production Candidate</p>
        <h1>{strategy?.name ?? "全部策略"}</h1>
      </div>
      <div className="top-actions">
        <select value={data.selectedStrategyId} onChange={(event) => data.selectStrategy(event.target.value)}>
          <option value="ALL">全部策略</option>
          {data.strategies.map((item) => (
            <option key={item.strategy_id} value={item.strategy_id}>
              {item.name}
            </option>
          ))}
        </select>
        <span className="date-pill">{tradeDate}</span>
        <span className={`status ${riskTone(status)}`}>{status}</span>
      </div>
    </header>
  );
}
