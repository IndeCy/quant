import type { DataQualityGateResult, DataQualityGateSummary } from "./model";

export function catalogTone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (status === "OK") {
    return "success";
  }
  if (status === "ERROR" || status === "FAIL") {
    return "danger";
  }
  if (status === "WARN" || status === "WARNING") {
    return "warning";
  }
  return "neutral";
}

export function formatBytes(size: number): string {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  if (size < 1024 * 1024 * 1024) {
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
  }
  return `${(size / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

export function qualityGateSummary(result: DataQualityGateResult | null): DataQualityGateSummary {
  if (!result) {
    return { label: "未运行", tone: "neutral" };
  }
  if (result.status === "PASS") {
    return { label: `${result.check_count} checks passed`, tone: "success" };
  }
  return { label: `${result.failed_count}/${result.check_count} failed`, tone: "danger" };
}
