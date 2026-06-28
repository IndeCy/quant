import { getJson } from "../../shared/api/client";
import type { MarketMetric } from "./model";

export function getMarketSeries(benchmarkId: string): Promise<MarketMetric[]> {
  return getJson<MarketMetric[]>(`/api/series/market/${benchmarkId}`);
}
