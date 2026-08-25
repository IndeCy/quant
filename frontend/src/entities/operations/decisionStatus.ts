import type { OperationsDecisionSeverity, OperationsDecisionState } from "./decisionModel";

export function decisionTitle(decision: OperationsDecisionState): string {
  return decision === "NO_ACTION" ? "今日无需人工处理" : "需要人工处理";
}

export function decisionTone(severity: OperationsDecisionSeverity): "success" | "warning" | "danger" {
  if (severity === "CRITICAL") return "danger";
  if (severity === "WARNING") return "warning";
  return "success";
}
