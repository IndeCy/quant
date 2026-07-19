export type RiskConfirmationDecision = "" | "REDUCE" | "PROCEED" | "PAUSE";

export interface RiskConfirmationTask {
  trade_date: string;
  previous_trade_date: string;
  strategy_id: string;
  strategy_name: string;
  severity: "WARNING" | "CRITICAL";
  status: "PENDING_MANUAL_CONFIRM" | "CONFIRMED_REDUCE" | "CONFIRMED_PROCEED" | "CONFIRMED_PAUSE";
  decision: RiskConfirmationDecision;
  current_exposure: number;
  recommended_max_exposure: number;
  recommended_target_exposure: number;
  daily_return: number;
  drawdown: number;
  volatility_20: number;
  tradability_check: string;
  suggested_action: string;
  reasons: string;
}

export interface RiskConfirmationState {
  trade_date: string;
  previous_trade_date: string;
  status: "NO_ACTION" | "NEED_CONFIRM" | "REDUCTION_READY" | "READY" | "PAUSED";
  task_count: number;
  pending_count: number;
  tasks: RiskConfirmationTask[];
}
