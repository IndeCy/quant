export type ObservationStatus = "PASS" | "WARN" | "FAIL";

export interface OperationsObservation {
  repo_root: string;
  generated_at: string;
  latest_activity_date: string;
  latest_activity_type: string;
  latest_run_date: string;
  ready_for_daily_review: boolean;
  summary: {
    pass: number;
    warn: number;
    fail: number;
  };
  run_artifacts: Record<string, ObservationStatus>;
  scheduler: Record<string, ObservationStatus>;
  notification: {
    configured: boolean;
    status: ObservationStatus;
    details: string;
  };
  held_reports: Record<string, ObservationStatus>;
}
