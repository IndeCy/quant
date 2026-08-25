export type RiskConfirmationDecision = "" | "REDUCE" | "PROCEED" | "PAUSE";

export interface RiskConfirmationTask {
  trade_date: string;
  previous_trade_date: string;
  strategy_id: string;
  strategy_name: string;
  severity: "WARNING" | "CRITICAL";
  status: "PENDING_MANUAL_CONFIRM" | "CONFIRMED_REDUCE" | "CONFIRMED_PROCEED" | "CONFIRMED_PAUSE" | "RISK_CONTROLLED";
  decision: RiskConfirmationDecision;
  current_exposure: number;
  recommended_max_exposure: number;
  recommended_target_exposure: number;
  active_risk_cap?: number | null;
  effective_target_exposure?: number | null;
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
  status: "NO_ACTION" | "NEED_CONFIRM" | "REDUCTION_READY" | "READY" | "PAUSED" | "RISK_CONTROLLED";
  task_count: number;
  pending_count: number;
  tasks: RiskConfirmationTask[];
  recovery: RiskRecoveryState;
  execution?: {
    status: string;
    message: string;
    executed_orders?: number;
    rejected_orders?: number;
    cancelled_orders?: number;
    risk_reduction_orders?: number;
  };
  recovery_execution?: {
    execution?: {
      status: string;
      message?: string;
      created_orders?: number;
      cancelled_orders?: number;
      next_trade_date?: string;
    };
  };
}

export interface RiskRecoveryTask {
  recommendation_id: string;
  strategy_id: string;
  strategy_name: string;
  trade_date: string;
  current_cap: number;
  recommended_cap: number;
  recommendation_action: "INCREASE" | "RELEASE";
  current_severity: "NORMAL" | "WARNING" | "CRITICAL";
  stable_days_observed: number;
  stable_days_required: number;
  drawdown_recovery: number;
  latest_drawdown: number;
  latest_volatility_20: number;
  eligible: boolean;
  reason: string;
  status: "MONITORING" | "PENDING_CONFIRM";
}

export interface RiskRecoveryState {
  trade_date: string;
  pending_count: number;
  tasks: RiskRecoveryTask[];
}
