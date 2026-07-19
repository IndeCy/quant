import { getBackupManifest } from "../entities/backup/api";
import { getEnvironmentAudit } from "../entities/environment/api";
import { listFactors } from "../entities/factor/api";
import { listLogs } from "../entities/log/api";
import { getLatestMarketBeta, getMarketSeries } from "../entities/market/api";
import { listOperationsAcknowledgements } from "../entities/operations/ackApi";
import { getOperationsDecision } from "../entities/operations/decisionApi";
import { getOperationsObservation } from "../entities/operations/api";
import { getOperationsReview } from "../entities/operations/reviewApi";
import { getReadinessReport } from "../entities/readiness/api";
import { getRiskConfirmations } from "../entities/riskConfirmation/api";
import { listReports } from "../entities/report/api";
import {
  getResearchTodos,
  getHotMoneyLeaders,
  listFactorIdeas,
  listOpportunityRankings,
  listOpportunityThemes,
  listResearchNotes,
  listStrategyIdeas
} from "../entities/research/api";
import { listRuns } from "../entities/run/api";
import { getSchedulerStatus } from "../entities/scheduler/api";
import { getServiceManifest, getServiceStatus } from "../entities/service/api";
import {
  getStrategy,
  getStrategySeries,
  listStrategies,
  listStrategyInstances,
  listStrategyTemplates
} from "../entities/strategy/api";
import { listStrategyDrafts } from "../entities/strategyDraft/api";
import { chooseDefaultStrategyId } from "./state";

export async function loadDashboardData() {
  const strategies = await listStrategies();
  const strategyIds = strategies.map((item) => item.strategy_id);
  const strategyDetailsList = await Promise.all(strategyIds.map((strategyId) => getStrategy(strategyId)));
  const strategySeriesList = await Promise.all(strategyIds.map((strategyId) => getStrategySeries(strategyId)));
  const strategyDetails = Object.fromEntries(strategyDetailsList.map((item) => [item.strategy_id, item]));
  const strategySeriesMap = Object.fromEntries(strategyIds.map((strategyId, index) => [strategyId, strategySeriesList[index]]));
  const strategyId = chooseDefaultStrategyId(strategyDetailsList);
  const [
    backupManifest,
    environmentAudit,
    factors,
    logs,
    operationsAcknowledgements,
    operationsDecision,
    operationsObservation,
    operationsReview,
    reports,
    researchTodos,
    hotMoneyLeaders,
    researchNotes,
    opportunityThemes,
    opportunityRankings,
    factorIdeas,
    strategyIdeas,
    runs,
    schedulerStatus,
    serviceManifest,
    serviceStatus,
    strategyDrafts,
    strategyTemplates,
    strategyInstances,
    marketSeries,
    marketBeta,
    readiness,
    riskConfirmations
  ] = await Promise.all([
    getBackupManifest(),
    getEnvironmentAudit(),
    listFactors(),
    listLogs(),
    listOperationsAcknowledgements(),
    getOperationsDecision(),
    getOperationsObservation(),
    getOperationsReview(),
    listReports(),
    getResearchTodos(),
    getHotMoneyLeaders(),
    listResearchNotes(),
    listOpportunityThemes(),
    listOpportunityRankings(),
    listFactorIdeas(),
    listStrategyIdeas(),
    listRuns(),
    getSchedulerStatus(),
    getServiceManifest(),
    getServiceStatus(),
    listStrategyDrafts(),
    listStrategyTemplates(),
    listStrategyInstances(),
    getMarketSeries("510300"),
    getLatestMarketBeta(),
    getReadinessReport(),
    getRiskConfirmations()
  ]);
  const strategy = strategyDetails[strategyId] ?? strategyDetailsList[0];
  const strategySeries = strategySeriesMap[strategyId] ?? [];
  return {
    strategies,
    backupManifest,
    environmentAudit,
    strategy,
    factors,
    logs,
    operationsAcknowledgements,
    operationsDecision,
    operationsObservation,
    operationsReview,
    reports,
    researchTodos,
    hotMoneyLeaders,
    researchNotes,
    opportunityThemes,
    opportunityRankings,
    factorIdeas,
    strategyIdeas,
    runs,
    schedulerStatus,
    serviceManifest,
    serviceStatus,
    strategyDrafts,
    strategyTemplates,
    strategyInstances,
    strategySeries,
    strategyDetails,
    strategySeriesMap,
    marketSeries,
    marketBeta,
    readiness,
    riskConfirmations
  };
}
