import type { ReadinessState } from "./model";

const checkLabels: Record<string, string> = {
  tushare_token: "Tushare Token",
  live_market_data: "行情增量数据",
  benchmark_data: "基准数据",
  monitoring_db: "监控库",
  system_state_db: "系统状态库",
  scheduler_job: "每日任务",
  api_service: "API 服务",
  frontend_service: "前端服务",
  scheduler_service: "调度器服务",
  backup_manifest: "备份清单",
  notification_channel: "Bark 通知",
  manual_order_workflow: "手工调仓闭环",
  broker_permission_boundary: "券商权限边界"
};

export function readinessTitle(status: ReadinessState): string {
  return status === "READY" ? "可连续运行" : "需要处理";
}

export function readinessTone(status: ReadinessState): "success" | "danger" {
  return status === "READY" ? "success" : "danger";
}

export function readinessCheckLabel(name: string): string {
  return checkLabels[name] ?? name;
}
