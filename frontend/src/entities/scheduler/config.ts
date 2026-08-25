export function validateSchedulerConfig(hour: number, minute: number): { valid: boolean; message: string } {
  if (!Number.isInteger(hour) || hour < 0 || hour > 23) {
    return { valid: false, message: "小时必须在 0-23 之间" };
  }
  if (!Number.isInteger(minute) || minute < 0 || minute > 59) {
    return { valid: false, message: "分钟必须在 0-59 之间" };
  }
  return { valid: true, message: "调度时间有效" };
}
