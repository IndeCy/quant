export type OperationsDecisionState = "NO_ACTION" | "ACTION_REQUIRED";
export type OperationsDecisionSeverity = "NORMAL" | "WARNING" | "CRITICAL";

export interface OperationsAction {
  source: string;
  category: string;
  name: string;
  severity: OperationsDecisionSeverity;
  message: string;
  suggested_action: string;
}

export interface OperationsDecision {
  repo_root: string;
  generated_at: string;
  decision: OperationsDecisionState;
  severity: OperationsDecisionSeverity;
  manual_intervention_required: boolean;
  latest_run_date: string;
  latest_activity_date: string;
  latest_activity_type: string;
  summary: {
    pass: number;
    warn: number;
    fail: number;
  };
  next_action: string;
  actions: OperationsAction[];
}
