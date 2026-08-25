import { getJson } from "../../shared/api/client";
import type { ReportContent, ReportIndex } from "./model";

export function listReports(strategyId?: string): Promise<ReportIndex[]> {
  const query = strategyId ? `?strategy_id=${encodeURIComponent(strategyId)}` : "";
  return getJson<ReportIndex[]>(`/api/reports${query}`);
}

export function getReportContent(reportId: string): Promise<ReportContent> {
  return getJson<ReportContent>(`/api/reports/${encodeURIComponent(reportId)}`);
}
