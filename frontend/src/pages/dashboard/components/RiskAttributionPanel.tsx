import type { StrategyMetric } from "../../../entities/strategy/model";
import { formatPercent } from "../../../shared/lib/formatters";

interface RiskAttributionPanelProps {
  rows: StrategyMetric[];
}

const ATTRIBUTION_LABELS = {
  RISK_AVOIDED_LOSS: "避免损失",
  RISK_REENTRY_DRAG: "反弹机会成本",
  NEUTRAL: "无风险层影响"
} as const;

export function RiskAttributionPanel({ rows }: RiskAttributionPanelProps) {
  const latest = [...rows]
    .reverse()
    .find((row) => typeof row.paper_daily_return === "number" && typeof row.risk_adjusted_daily_return === "number");
  if (!latest) {
    return null;
  }
  const label = ATTRIBUTION_LABELS[latest.risk_attribution_type ?? "NEUTRAL"];
  return (
    <section className="panel compact">
      <div className="panel-title-row">
        <h2>当日收益归因</h2>
        <span className="status neutral">{label}</span>
      </div>
      <dl>
        <div><dt>Alpha理论收益</dt><dd>{formatPercent(latest.daily_return)}</dd></div>
        <div><dt>风险调整后收益</dt><dd>{formatPercent(latest.risk_adjusted_daily_return)}</dd></div>
        <div><dt>风险层贡献</dt><dd>{formatPercent(latest.risk_overlay_contribution)}</dd></div>
        <div><dt>执行跟踪贡献</dt><dd>{formatPercent(latest.execution_tracking_contribution)}</dd></div>
        <div><dt>估算交易成本</dt><dd>{formatPercent(latest.trading_cost_contribution)}</dd></div>
        <div><dt>Paper实际收益</dt><dd>{formatPercent(latest.paper_daily_return)}</dd></div>
        <div><dt>策略理论仓位</dt><dd>{formatPercent(latest.exposure)}</dd></div>
        <div><dt>有效风险上限</dt><dd>{formatPercent(latest.risk_cap)}</dd></div>
        <div><dt>有效目标仓位</dt><dd>{formatPercent(latest.effective_exposure)}</dd></div>
        <div><dt>Paper实际仓位</dt><dd>{formatPercent(latest.paper_exposure)}</dd></div>
      </dl>
    </section>
  );
}
