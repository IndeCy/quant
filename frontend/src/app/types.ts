import type { BackupManifest } from "../entities/backup/model";
import type { FactorDefinition } from "../entities/factor/model";
import type { RuntimeLog } from "../entities/log/model";
import type { MarketMetric } from "../entities/market/model";
import type { OperationsAcknowledgement } from "../entities/operations/ackModel";
import type { OperationsDecision } from "../entities/operations/decisionModel";
import type { OperationsObservation } from "../entities/operations/model";
import type { ReadinessReport } from "../entities/readiness/model";
import type { ReportIndex } from "../entities/report/model";
import type {
  FactorIdea,
  OpportunityRanking,
  OpportunityTheme,
  ResearchNote,
  ResearchTodos,
  StrategyIdea
} from "../entities/research/model";
import type { StrategyRun } from "../entities/run/model";
import type { SchedulerStatus } from "../entities/scheduler/model";
import type { ServiceManifest, ServiceStatusManifest } from "../entities/service/model";
import type { StrategyDefinition, StrategyInstance, StrategyMetric, StrategyTemplate } from "../entities/strategy/model";
import type { StrategyDraft } from "../entities/strategyDraft/model";

export interface DashboardData {
  strategies: StrategyDefinition[];
  backupManifest: BackupManifest;
  strategy: StrategyDefinition;
  factors: FactorDefinition[];
  logs: RuntimeLog[];
  operationsAcknowledgements: OperationsAcknowledgement[];
  operationsDecision: OperationsDecision;
  operationsObservation: OperationsObservation;
  reports: ReportIndex[];
  researchTodos: ResearchTodos;
  researchNotes: ResearchNote[];
  opportunityThemes: OpportunityTheme[];
  opportunityRankings: OpportunityRanking[];
  factorIdeas: FactorIdea[];
  strategyIdeas: StrategyIdea[];
  runs: StrategyRun[];
  schedulerStatus: SchedulerStatus;
  serviceManifest: ServiceManifest;
  serviceStatus: ServiceStatusManifest;
  strategyDrafts: StrategyDraft[];
  strategyTemplates: StrategyTemplate[];
  strategyInstances: StrategyInstance[];
  strategySeries: StrategyMetric[];
  strategyDetails: Record<string, StrategyDefinition>;
  strategySeriesMap: Record<string, StrategyMetric[]>;
  marketSeries: MarketMetric[];
  readiness: ReadinessReport;
}

export interface DashboardContext extends DashboardData {
  selectedStrategyId: string;
  refreshData: () => Promise<void>;
  selectStrategy: (strategyId: string) => void;
  updateRuntimeStatus: (schedulerStatus: SchedulerStatus, readiness: ReadinessReport) => void;
}
