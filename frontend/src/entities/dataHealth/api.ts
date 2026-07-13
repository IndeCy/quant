import { getJson } from "../../shared/api/client";
import type { DataHealth } from "./model";

export function getDataHealth(): Promise<DataHealth> {
  return getJson<DataHealth>("/api/data/health");
}
