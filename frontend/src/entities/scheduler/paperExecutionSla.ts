import { getJson } from "../../shared/api/client";

export interface PaperExecutionSlaDay {
  trade_date: string;
  status: "SUCCESS" | "FAILED" | "NOT_APPLICABLE";
  run_status: string;
  due_orders: number;
  filled_orders: number;
  rejected_orders: number;
  cancelled_orders: number;
  pending_orders: number;
  late_orders: number;
  issues: string[];
}

export interface PaperExecutionSlaProgress {
  gate_status: "PASSED" | "OBSERVING";
  required_days: number;
  current_streak: number;
  remaining_days: number;
  longest_streak: number;
  observed_days: number;
  success_days: number;
  failed_days: number;
  missing_days: number;
  pass_rate: number;
  latest_trade_date: string;
  latest_status: string;
  latest_issues: string[];
}

export interface PaperExecutionSlaView {
  progress: PaperExecutionSlaProgress;
  history: PaperExecutionSlaDay[];
  strategies: StrategyPaperObservationView[];
}

export interface StrategyPaperObservationProgress {
  strategy_id: string;
  gate_status: "PASSED" | "OBSERVING";
  required_days: number;
  current_streak: number;
  remaining_days: number;
  observed_days: number;
  success_days: number;
  failed_days: number;
  latest_trade_date: string;
  latest_status: string;
  latest_issues: string[];
}

export interface StrategyPaperObservationView {
  strategy_id: string;
  strategy_name: string;
  progress: StrategyPaperObservationProgress;
  history: Array<{
    trade_date: string;
    status: "SUCCESS" | "FAILED" | "NOT_APPLICABLE";
    strategy_run_status: string;
    execution_run_status: string;
    due_orders: number;
    filled_orders: number;
    rejected_orders: number;
    pending_orders: number;
    late_orders: number;
    issues: string[];
  }>;
}

export function getPaperExecutionSla(): Promise<PaperExecutionSlaView> {
  return getJson<PaperExecutionSlaView>("/api/scheduler/paper-execution-sla");
}
