export interface FactorContract {
  factor_id: string;
  name?: string;
  category?: string;
  direction?: string;
  source?: string;
  description?: string;
  version: string;
  status: string;
  frequency: string;
  value_type: string;
  as_of_policy: string;
  as_of_field: string;
  effective_date_field: string;
  lag_days: number;
  input_datasets: string[];
  input_fields: string[];
  output_fields: string[];
  dependencies: string[];
  validation: Record<string, string | number | boolean>;
  owner?: string;
}
