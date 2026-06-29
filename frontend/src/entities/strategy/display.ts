import { formatPercent } from "../../shared/lib/formatters";
import type { StrategyMetric } from "./model";

type StrategyMetricKey = "trade_date" | "cumulative_return" | "drawdown";

export function strategyMetricText(metric: Partial<StrategyMetric> | null | undefined, key: StrategyMetricKey): string {
  if (!metric || metric[key] === undefined || metric[key] === null) {
    return "-";
  }
  if (key === "trade_date") {
    return String(metric.trade_date);
  }
  return formatPercent(metric[key]);
}
