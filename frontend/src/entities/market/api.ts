import { getJson } from "../../shared/api/client";
import type { MarketBetaSnapshot, MarketIndexComparison, MarketMetric, MarketStyleOverview } from "./model";

export function getMarketSeries(benchmarkId: string): Promise<MarketMetric[]> {
  return getJson<MarketMetric[]>(`/api/series/market/${benchmarkId}`);
}

export function getLatestMarketBeta(): Promise<MarketBetaSnapshot> {
  return getJson<MarketBetaSnapshot>("/api/market/beta/latest");
}

export function getMarketIndexComparison(limit = 5000): Promise<MarketIndexComparison> {
  return getJson<MarketIndexComparison>(`/api/market/index-comparison?limit=${limit}`);
}

export function getMarketStyleOverview(limit = 240): Promise<MarketStyleOverview> {
  return getJson<MarketStyleOverview>(`/api/market/style-overview?limit=${limit}`);
}
