import type { EnvironmentAuditState } from "./model";

export function environmentAuditTitle(status: EnvironmentAuditState): string {
  return status === "PASS" ? "环境一致" : "环境漂移";
}

export function environmentAuditTone(status: EnvironmentAuditState): "success" | "danger" {
  return status === "PASS" ? "success" : "danger";
}

export function sourceLabel(source: string): string {
  const labels: Record<string, string> = {
    process: "API进程",
    api_launchd: "API Launchd",
    scheduler_launchd: "调度 Launchd",
    frontend_launchd: "前端 Launchd"
  };
  return labels[source] ?? source;
}
