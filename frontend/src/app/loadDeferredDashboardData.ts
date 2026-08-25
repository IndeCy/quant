import { getBackupManifest } from "../entities/backup/api";
import { getEnvironmentAudit } from "../entities/environment/api";
import { listExperiments } from "../entities/experiment/api";
import { listFactors } from "../entities/factor/api";
import { listLogs } from "../entities/log/api";
import { listOperationsAcknowledgements } from "../entities/operations/ackApi";
import { getOperationsDecision } from "../entities/operations/decisionApi";
import { getOperationsObservation } from "../entities/operations/api";
import { getOperationsReview } from "../entities/operations/reviewApi";
import { getRiskConfirmations } from "../entities/riskConfirmation/api";
import {
  getResearchTodos,
  getHotMoneyLeaders,
  listFactorIdeas,
  listOpportunityRankings,
  listOpportunityThemes,
  listResearchNotes,
  listStrategyIdeas
} from "../entities/research/api";
import { getSchedulerStatus } from "../entities/scheduler/api";
import { getPaperExecutionSla } from "../entities/scheduler/paperExecutionSla";
import { getServiceManifest, getServiceStatus } from "../entities/service/api";
import { listStrategyInstances, listStrategyTemplates } from "../entities/strategy/api";
import { listStrategyDrafts } from "../entities/strategyDraft/api";
import type { DashboardDeferredData } from "./types";

export async function loadDeferredDashboardData(): Promise<DashboardDeferredData> {
  const [
    backupManifest,
    environmentAudit,
    experiments,
    factors,
    logs,
    operationsAcknowledgements,
    operationsDecision,
    operationsObservation,
    operationsReview,
    researchTodos,
    hotMoneyLeaders,
    researchNotes,
    opportunityThemes,
    opportunityRankings,
    factorIdeas,
    strategyIdeas,
    schedulerStatus,
    paperExecutionSla,
    serviceManifest,
    serviceStatus,
    strategyDrafts,
    strategyTemplates,
    strategyInstances,
    riskConfirmations
  ] = await Promise.all([
    getBackupManifest(),
    getEnvironmentAudit(),
    listExperiments(),
    listFactors(),
    listLogs(),
    listOperationsAcknowledgements(),
    getOperationsDecision(),
    getOperationsObservation(),
    getOperationsReview(),
    getResearchTodos(),
    getHotMoneyLeaders(),
    listResearchNotes(),
    listOpportunityThemes(),
    listOpportunityRankings(),
    listFactorIdeas(),
    listStrategyIdeas(),
    getSchedulerStatus(),
    getPaperExecutionSla(),
    getServiceManifest(),
    getServiceStatus(),
    listStrategyDrafts(),
    listStrategyTemplates(),
    listStrategyInstances(),
    getRiskConfirmations()
  ]);
  return {
    backupManifest,
    environmentAudit,
    experiments,
    factors,
    logs,
    operationsAcknowledgements,
    operationsDecision,
    operationsObservation,
    operationsReview,
    researchTodos,
    hotMoneyLeaders,
    researchNotes,
    opportunityThemes,
    opportunityRankings,
    factorIdeas,
    strategyIdeas,
    schedulerStatus,
    paperExecutionSla,
    serviceManifest,
    serviceStatus,
    strategyDrafts,
    strategyTemplates,
    strategyInstances,
    riskConfirmations
  };
}
