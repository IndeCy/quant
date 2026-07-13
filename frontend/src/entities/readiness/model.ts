export type ReadinessState = "READY" | "NOT_READY";

export type ReadinessCheckState = "PASS" | "FAIL";

export interface ReadinessCheck {
  name: string;
  status: ReadinessCheckState;
  message: string;
}

export interface ReadinessReport {
  status: ReadinessState;
  checks: ReadinessCheck[];
}
