import { getJson, postJson } from "../../shared/api/client";
import type { DataCatalogRefreshResult, DataQualityGateResult, DataSource, DataSourceDetail } from "./model";

export function refreshDataCatalog(): Promise<DataCatalogRefreshResult> {
  return postJson<DataCatalogRefreshResult>("/api/data/catalog/refresh", {});
}

export function listDataSources(): Promise<DataSource[]> {
  return getJson<DataSource[]>("/api/data/sources");
}

export function getDataSource(datasetId: string): Promise<DataSourceDetail> {
  return getJson<DataSourceDetail>(`/api/data/sources/${datasetId}`);
}

export function runDataQualityGate(minTradeDate?: string): Promise<DataQualityGateResult> {
  return postJson<DataQualityGateResult>("/api/data/quality-gate", minTradeDate ? { min_trade_date: minTradeDate } : {});
}
