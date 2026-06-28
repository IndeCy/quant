import type { StrategyDefinition } from "../../entities/strategy/model";
import { riskTone } from "../../shared/lib/formatters";

interface TopStatusBarProps {
  strategy?: StrategyDefinition | null;
}

export function TopStatusBar({ strategy }: TopStatusBarProps) {
  const status = strategy?.latest_run?.status ?? strategy?.status ?? "UNKNOWN";
  const tradeDate = strategy?.latest_metrics?.trade_date ?? "-";
  return (
    <header className="top-status">
      <div>
        <p className="eyebrow">Production Candidate</p>
        <h1>{strategy?.name ?? "Quant Console"}</h1>
      </div>
      <div className="top-actions">
        <span className="date-pill">{tradeDate}</span>
        <span className={`status ${riskTone(status)}`}>{status}</span>
      </div>
    </header>
  );
}
