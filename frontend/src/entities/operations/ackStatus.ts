import type { OperationsAckStatus } from "./ackModel";

export function ackStatusTone(status: OperationsAckStatus | string): "success" | "neutral" {
  if (status === "ACKNOWLEDGED" || status === "RESOLVED") return "success";
  return "neutral";
}
