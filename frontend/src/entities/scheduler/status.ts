export function schedulerStateLabel(enabled: boolean, jobStoreExists: boolean): string {
  if (enabled) {
    return "已配置";
  }
  return jobStoreExists ? "未登记任务" : "未初始化";
}

export function schedulerNextRunLabel(nextRunTime: string | null): string {
  if (!nextRunTime) {
    return "等待调度器启动";
  }
  return nextRunTime.replace("T", " ").replace("+08:00", "");
}
