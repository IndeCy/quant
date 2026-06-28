export interface SchedulerStatus {
  enabled: boolean;
  job_id: string;
  job_store_path: string;
  job_store_exists: boolean;
  next_run_time: string | null;
  schedule: string;
  start_command: string;
  log_path: string;
}

export interface SchedulerConfigPayload {
  hour: number;
  minute: number;
  skip_update: boolean;
  push: boolean;
}
