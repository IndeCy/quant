import { getJson } from "../../shared/api/client";
import type { OperationsDecision } from "./decisionModel";

export function getOperationsDecision(): Promise<OperationsDecision> {
  return getJson<OperationsDecision>("/api/operations/decision");
}
