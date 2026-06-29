import type { BackupManifest } from "../entities/backup/model";
import type { FactorDefinition } from "../entities/factor/model";
import type { RuntimeLog } from "../entities/log/model";
import type { MarketMetric } from "../entities/market/model";
import type { ReadinessReport } from "../entities/readiness/model";
import type { ReportIndex } from "../entities/report/model";
import type { ResearchTodos } from "../entities/research/model";
import type { StrategyRun } from "../entities/run/model";
import type { SchedulerStatus } from "../entities/scheduler/model";
import type { ServiceManifest, ServiceStatusManifest } from "../entities/service/model";
import type { StrategyDefinition, StrategyMetric } from "../entities/strategy/model";
import type { StrategyDraft } from "../entities/strategyDraft/model";

export interface DashboardData {
  strategies: StrategyDefinition[];
  backupManifest: BackupManifest;
  strategy: StrategyDefinition;
  factors: FactorDefinition[];
  logs: RuntimeLog[];
  reports: ReportIndex[];
  researchTodos: ResearchTodos;
  runs: StrategyRun[];
  schedulerStatus: SchedulerStatus;
  serviceManifest: ServiceManifest;
  serviceStatus: ServiceStatusManifest;
  strategyDrafts: StrategyDraft[];
  strategySeries: StrategyMetric[];
  marketSeries: MarketMetric[];
  readiness: ReadinessReport;
}
