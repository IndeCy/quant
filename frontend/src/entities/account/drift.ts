import { formatPercent } from "../../shared/lib/formatters";
import type { AccountPosition, AccountSnapshot } from "./model";

export function sortAccountPositions(positions: AccountPosition[]): AccountPosition[] {
  const actionRank: Record<string, number> = { BUY: 0, SELL: 1, HOLD: 2 };
  return [...positions].sort((left, right) => {
    const actionDiff = (actionRank[left.action] ?? 3) - (actionRank[right.action] ?? 3);
    if (actionDiff !== 0) {
      return actionDiff;
    }
    const driftDiff = Math.abs(right.drift_weight) - Math.abs(left.drift_weight);
    if (driftDiff !== 0) {
      return driftDiff;
    }
    return left.symbol.localeCompare(right.symbol);
  });
}

export function maxDriftLabel(snapshot?: Pick<AccountSnapshot, "max_abs_drift"> | null): string {
  return snapshot ? formatPercent(snapshot.max_abs_drift) : "-";
}
