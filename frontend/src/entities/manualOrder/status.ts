export function manualOrderStatusTone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (status === "CONFIRMED" || status === "FILLED") {
    return "success";
  }
  if (status === "DRAFT") {
    return "warning";
  }
  if (status === "REJECTED" || status === "CANCELLED") {
    return "danger";
  }
  return "neutral";
}

export function orderSideLabel(side: string): string {
  if (side === "BUY") {
    return "买入";
  }
  if (side === "SELL") {
    return "卖出";
  }
  return side || "-";
}
