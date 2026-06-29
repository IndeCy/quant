import { getBackupManifest } from "../entities/backup/api";
import { listFactors } from "../entities/factor/api";
import { listLogs } from "../entities/log/api";
import { getMarketSeries } from "../entities/market/api";
import { getReadinessReport } from "../entities/readiness/api";
import { listReports } from "../entities/report/api";
import { getResearchTodos } from "../entities/research/api";
import { listRuns } from "../entities/run/api";
import { getSchedulerStatus } from "../entities/scheduler/api";
import { getServiceManifest, getServiceStatus } from "../entities/service/api";
import { getStrategy, getStrategySeries, listStrategies } from "../entities/strategy/api";
import { listStrategyDrafts } from "../entities/strategyDraft/api";

export async function loadDashboardData() {
  const strategyId = "quality_overlay";
  const [
    strategies,
    backupManifest,
    strategy,
    factors,
    logs,
    reports,
    researchTodos,
    runs,
    schedulerStatus,
    serviceManifest,
    serviceStatus,
    strategyDrafts,
    strategySeries,
    marketSeries,
    readiness
  ] = await Promise.all([
    listStrategies(),
    getBackupManifest(),
    getStrategy(strategyId),
    listFactors(),
    listLogs(),
    listReports(strategyId),
    getResearchTodos(),
    listRuns(strategyId),
    getSchedulerStatus(),
    getServiceManifest(),
    getServiceStatus(),
    listStrategyDrafts(),
    getStrategySeries(strategyId),
    getMarketSeries("510300"),
    getReadinessReport()
  ]);
  return {
    strategies,
    backupManifest,
    strategy,
    factors,
    logs,
    reports,
    researchTodos,
    runs,
    schedulerStatus,
    serviceManifest,
    serviceStatus,
    strategyDrafts,
    strategySeries,
    marketSeries,
    readiness
  };
}
