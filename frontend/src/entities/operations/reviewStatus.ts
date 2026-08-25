import type { OperationsClosureStatus } from "./reviewModel";

export function reviewStatusTitle(status: OperationsClosureStatus): string {
  return status === "CLOSED" ? "闭环完成" : "仍需跟进";
}

export function reviewStatusTone(status: OperationsClosureStatus): "success" | "warning" {
  return status === "CLOSED" ? "success" : "warning";
}
