import { getJson } from "../../shared/api/client";
import type { ReadinessReport } from "./model";

export function getReadinessReport(): Promise<ReadinessReport> {
  return getJson<ReadinessReport>("/api/readiness");
}
