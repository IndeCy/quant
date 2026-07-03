import { getJson } from "../../shared/api/client";
import type { OperationsObservation } from "./model";

export function getOperationsObservation(): Promise<OperationsObservation> {
  return getJson<OperationsObservation>("/api/operations/observation");
}
