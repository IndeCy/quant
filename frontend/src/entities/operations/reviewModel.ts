import type { OperationsAction } from "./decisionModel";

export type OperationsClosureStatus = "OPEN" | "CLOSED";

export interface OperationsReview {
  repo_root: string;
  closure_status: OperationsClosureStatus;
  latest_decision: string;
  latest_severity: string;
  latest_run_date: string;
  latest_activity_date: string;
  current_action_count: number;
  acknowledged_action_count: number;
  unacknowledged_action_count: number;
  acknowledgement_count: number;
  latest_ack_at: string;
  unacknowledged_actions: OperationsAction[];
}
