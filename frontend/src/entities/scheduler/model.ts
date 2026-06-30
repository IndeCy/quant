export interface SchedulerStatus {
  enabled: boolean;
  job_id: string;
  job_store_path: string;
  job_store_exists: boolean;
  next_run_time: string | null;
  schedule: string;
  start_command: string;
  log_path: string;
  jobs: SchedulerJob[];
}

export interface SchedulerConfigPayload {
  hour: number;
  minute: number;
  skip_update: boolean;
  push: boolean;
}

export interface SchedulerJob {
  job_id: string;
  next_run_time: string | null;
  schedule: string;
  command: string[];
}
