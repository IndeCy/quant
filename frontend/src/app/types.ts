import type { BackupManifest } from "../entities/backup/model";
import type { FactorDefinition } from "../entities/factor/model";
import type { MarketMetric } from "../entities/market/model";
import type { ReportIndex } from "../entities/report/model";
import type { StrategyRun } from "../entities/run/model";
import type { SchedulerStatus } from "../entities/scheduler/model";
import type { StrategyDefinition, StrategyMetric } from "../entities/strategy/model";
import type { StrategyDraft } from "../entities/strategyDraft/model";

export interface DashboardData {
  strategies: StrategyDefinition[];
  backupManifest: BackupManifest;
  strategy: StrategyDefinition;
  factors: FactorDefinition[];
  reports: ReportIndex[];
  runs: StrategyRun[];
  schedulerStatus: SchedulerStatus;
  strategyDrafts: StrategyDraft[];
  strategySeries: StrategyMetric[];
  marketSeries: MarketMetric[];
}
