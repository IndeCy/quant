export type EnvironmentAuditState = "PASS" | "FAIL";

export interface EnvironmentValueSummary {
  present: boolean;
  fingerprint: string;
}

export interface EnvironmentAuditCheck {
  name: string;
  status: EnvironmentAuditState;
  required_sources: string[];
  missing_in: string[];
  mismatch_sources: string[];
  fingerprints: Record<string, string>;
  recommendation: string;
}

export interface EnvironmentAudit {
  status: EnvironmentAuditState;
  generated_at: string;
  secret_values_exposed: boolean;
  sources: Record<string, Record<string, EnvironmentValueSummary>>;
  checks: EnvironmentAuditCheck[];
}
