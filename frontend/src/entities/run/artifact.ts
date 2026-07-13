const artifactLabels: Record<string, string> = {
  daily_report: "日报",
  rebalance_plan: "调仓建议",
  portfolio_snapshot: "组合快照",
  strategy_metrics: "指标JSON"
};

export function runArtifactTypeLabel(reportType: string): string {
  return artifactLabels[reportType] ?? reportType;
}
