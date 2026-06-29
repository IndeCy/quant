import type { ReadinessState } from "./model";

export function readinessTitle(status: ReadinessState): string {
  return status === "READY" ? "可连续运行" : "需要处理";
}

export function readinessTone(status: ReadinessState): "success" | "danger" {
  return status === "READY" ? "success" : "danger";
}
