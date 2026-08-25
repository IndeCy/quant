import type { BackupManifest } from "../entities/backup/model";
import type { EnvironmentAudit } from "../entities/environment/model";
import type { ExperimentSummary } from "../entities/experiment/model";
import type { FactorDefinition } from "../entities/factor/model";
import type { RuntimeLog } from "../entities/log/model";
import type { MarketBetaSnapshot, MarketIndexComparison, MarketMetric } from "../entities/market/model";
import type { OperationsAcknowledgement } from "../entities/operations/ackModel";
import type { OperationsDecision } from "../entities/operations/decisionModel";
import type { OperationsObservation } from "../entities/operations/model";
import type { OperationsReview } from "../entities/operations/reviewModel";
import type { ReadinessReport } from "../entities/readiness/model";
import type { ReportIndex } from "../entities/report/model";
import type { RiskConfirmationState } from "../entities/riskConfirmation/model";
import type {
  FactorIdea,
  HotMoneyLeaderView,
  OpportunityRanking,
  OpportunityTheme,
  ResearchNote,
  ResearchTodos,
  StrategyIdea
} from "../entities/research/model";
import type { StrategyRun } from "../entities/run/model";
import type { SchedulerStatus } from "../entities/scheduler/model";
import type { PaperExecutionSlaView } from "../entities/scheduler/paperExecutionSla";
import type { ServiceManifest, ServiceStatusManifest } from "../entities/service/model";
import type {
  StrategyDefinition,
  StrategyInstance,
  StrategyInstanceState,
  StrategyMetric,
  StrategyTemplate
} from "../entities/strategy/model";
import type { StrategyDraft } from "../entities/strategyDraft/model";

export interface DashboardData {
  strategies: StrategyDefinition[];
  backupManifest: BackupManifest;
  environmentAudit: EnvironmentAudit;
  experiments: ExperimentSummary[];
  strategy: StrategyDefinition;
  factors: FactorDefinition[];
  logs: RuntimeLog[];
  operationsAcknowledgements: OperationsAcknowledgement[];
  operationsDecision: OperationsDecision;
  operationsObservation: OperationsObservation;
  operationsReview: OperationsReview;
  reports: ReportIndex[];
  researchTodos: ResearchTodos;
  hotMoneyLeaders: HotMoneyLeaderView;
  researchNotes: ResearchNote[];
  opportunityThemes: OpportunityTheme[];
  opportunityRankings: OpportunityRanking[];
  factorIdeas: FactorIdea[];
  strategyIdeas: StrategyIdea[];
  runs: StrategyRun[];
  schedulerStatus: SchedulerStatus;
  paperExecutionSla: PaperExecutionSlaView;
  serviceManifest: ServiceManifest;
  serviceStatus: ServiceStatusManifest;
  strategyDrafts: StrategyDraft[];
  strategyTemplates: StrategyTemplate[];
  strategyInstances: StrategyInstance[];
  strategyInstanceStates: Record<string, StrategyInstanceState>;
  strategySeries: StrategyMetric[];
  strategyDetails: Record<string, StrategyDefinition>;
  strategySeriesMap: Record<string, StrategyMetric[]>;
  marketIndexComparison: MarketIndexComparison;
  marketSeries: MarketMetric[];
  marketBeta: MarketBetaSnapshot;
  readiness: ReadinessReport;
  riskConfirmations: RiskConfirmationState;
}

export interface DashboardContext extends DashboardData {
  selectedStrategyId: string;
  refreshData: () => Promise<void>;
  selectStrategy: (strategyId: string) => void;
  updateRuntimeStatus: (schedulerStatus: SchedulerStatus, readiness: ReadinessReport) => void;
}

export type DashboardBootstrapData = Pick<
  DashboardData,
  | "strategies"
  | "strategy"
  | "reports"
  | "runs"
  | "strategySeries"
  | "strategyDetails"
  | "strategySeriesMap"
  | "strategyInstanceStates"
  | "marketIndexComparison"
  | "marketSeries"
  | "marketBeta"
  | "readiness"
>;

export type DashboardDeferredData = Omit<DashboardData, keyof DashboardBootstrapData>;
