export interface DataSourceTable {
  dataset_id?: string;
  table_name: string;
  row_count: number;
  date_field: string;
  latest_date: string;
  columns: string[];
  status: string;
}

export interface DataSource {
  dataset_id: string;
  file_path: string;
  database_type: string;
  size_bytes: number;
  status: string;
  latest_date: string;
  description?: string;
  config?: Record<string, string | number | boolean>;
  tables?: DataSourceTable[];
}

export interface DataSourceDetail extends DataSource {
  tables: DataSourceTable[];
}

export interface DataCatalogRefreshResult {
  status: string;
  source_count: number;
  ok_count: number;
  error_count: number;
}

export interface DataQualityGateCheck {
  dataset_id: string;
  table_name: string;
  status: string;
  latest_date: string;
  message: string;
}

export interface DataQualityGateResult {
  status: "PASS" | "FAIL" | string;
  check_count: number;
  failed_count: number;
  checks: DataQualityGateCheck[];
}

export interface DataQualityGateSummary {
  label: string;
  tone: "success" | "warning" | "danger" | "neutral";
}
