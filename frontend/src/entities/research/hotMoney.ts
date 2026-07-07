export function hotMoneyStatusLabel(status: string): string {
  if (status === "READY") {
    return "已生成";
  }
  if (status === "MISSING_CACHE") {
    return "缺少缓存";
  }
  if (status === "NO_DATA") {
    return "暂无数据";
  }
  if (status === "NO_LIMIT_UP") {
    return "无涨停样本";
  }
  return "未运行";
}
