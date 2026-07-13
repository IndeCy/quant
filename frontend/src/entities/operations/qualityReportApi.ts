import { postJson } from "../../shared/api/client";

export interface OperationsQualityReportResult {
  trade_date: string;
  markdown_path: string;
  json_path: string;
}

export function generateOperationsQualityReport(tradeDate?: string): Promise<OperationsQualityReportResult> {
  return postJson<OperationsQualityReportResult>("/api/operations/quality-report", { trade_date: tradeDate ?? "" });
}
