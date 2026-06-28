import { getBackupManifest } from "../entities/backup/api";
import { listFactors } from "../entities/factor/api";
import { getMarketSeries } from "../entities/market/api";
import { listReports } from "../entities/report/api";
import { listRuns } from "../entities/run/api";
import { getSchedulerStatus } from "../entities/scheduler/api";
import { getStrategy, getStrategySeries, listStrategies } from "../entities/strategy/api";
import { listStrategyDrafts } from "../entities/strategyDraft/api";

export async function loadDashboardData() {
  const strategyId = "quality_overlay";
  const [strategies, backupManifest, strategy, factors, reports, runs, schedulerStatus, strategyDrafts, strategySeries, marketSeries] = await Promise.all([
    listStrategies(),
    getBackupManifest(),
    getStrategy(strategyId),
    listFactors(),
    listReports(strategyId),
    listRuns(strategyId),
    getSchedulerStatus(),
    listStrategyDrafts(),
    getStrategySeries(strategyId),
    getMarketSeries("510300")
  ]);
  return { strategies, backupManifest, strategy, factors, reports, runs, schedulerStatus, strategyDrafts, strategySeries, marketSeries };
}
