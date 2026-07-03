import { getJson } from "../../shared/api/client";
import type { EnvironmentAudit } from "./model";

export function getEnvironmentAudit(): Promise<EnvironmentAudit> {
  return getJson<EnvironmentAudit>("/api/environment/audit");
}
