import { getJson } from "../../shared/api/client";
import type { RuntimeLog, RuntimeLogContent } from "./model";

export function listLogs(): Promise<RuntimeLog[]> {
  return getJson<RuntimeLog[]>("/api/logs");
}

export function getLogContent(logId: string): Promise<RuntimeLogContent> {
  return getJson<RuntimeLogContent>(`/api/logs/${logId}`);
}
