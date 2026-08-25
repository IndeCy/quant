export interface RuntimeLog {
  log_id: string;
  log_type: string;
  name: string;
  path: string;
  size_bytes: number;
  modified_at: number;
  runtime_root: string;
}

export interface RuntimeLogContent extends RuntimeLog {
  content: string;
}
