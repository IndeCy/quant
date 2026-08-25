export interface ExperimentArtifact {
  artifact_id: string;
  run_id: string;
  artifact_type: string;
  file_path: string;
  title: string;
  preview?: string;
}

export interface ExperimentRun {
  run_id: string;
  experiment_id: string;
  run_date: string;
  status: string;
  output_dir: string;
  config: Record<string, unknown>;
  metrics: Record<string, unknown>;
  message: string;
  definition_fingerprint: string;
  run_fingerprint: string;
  data_as_of: string;
  data_version: string;
  outcome: string;
  decision_reason: string;
  reused_from_run_id: string;
  reuse_count: number;
  last_reused_at: string;
  artifacts: ExperimentArtifact[];
}

export interface ExperimentSummary {
  experiment_id: string;
  name: string;
  category: string;
  status: string;
  owner: string;
  description: string;
  hypothesis: string;
  definition_fingerprint: string;
  config: Record<string, unknown>;
  latest_run_id?: string;
  latest_run_date?: string;
  latest_run_status?: string;
  latest_metrics: Record<string, unknown>;
  latest_message?: string;
  latest_data_as_of?: string;
  latest_outcome?: string;
  latest_decision_reason?: string;
  latest_definition_fingerprint?: string;
  latest_run_fingerprint?: string;
  latest_reuse_count?: number;
}

export interface ExperimentDetail extends ExperimentSummary {
  runs: ExperimentRun[];
  latest_run: ExperimentRun | null;
}
