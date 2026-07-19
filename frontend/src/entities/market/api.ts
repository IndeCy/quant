import { getJson } from "../../shared/api/client";
import type { MarketBetaSnapshot, MarketMetric, MarketStyleOverview } from "./model";

export function getMarketSeries(benchmarkId: string): Promise<MarketMetric[]> {
  return getJson<MarketMetric[]>(`/api/series/market/${benchmarkId}`);
}

export function getLatestMarketBeta(): Promise<MarketBetaSnapshot> {
  return getJson<MarketBetaSnapshot>("/api/market/beta/latest");
}

export function getMarketStyleOverview(limit = 240): Promise<MarketStyleOverview> {
  return getJson<MarketStyleOverview>(`/api/market/style-overview?limit=${limit}`);
}
