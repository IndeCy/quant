import { getJson, postJson } from "../../shared/api/client";
import type { RiskConfirmationDecision, RiskConfirmationState } from "./model";

export function getRiskConfirmations(): Promise<RiskConfirmationState> {
  return getJson<RiskConfirmationState>("/api/risk-confirmations");
}

export function confirmStrategyRisk(
  strategyId: string,
  tradeDate: string,
  decision: Exclude<RiskConfirmationDecision, "">
): Promise<RiskConfirmationState> {
  return postJson<RiskConfirmationState>(`/api/risk-confirmations/${strategyId}`, {
    trade_date: tradeDate,
    decision
  });
}
