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

export function formatHotMoneyTradeDate(value: string): string {
  if (!value || value.length !== 8) {
    return "-";
  }
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
}
