export function logTypeLabel(logType: string): string {
  if (logType === "run") {
    return "流水线";
  }
  if (logType === "service") {
    return "服务";
  }
  return logType;
}
