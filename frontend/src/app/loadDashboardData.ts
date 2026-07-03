import { getBackupManifest } from "../entities/backup/api";
import { listFactors } from "../entities/factor/api";
import { listLogs } from "../entities/log/api";
import { getMarketSeries } from "../entities/market/api";
import { listOperationsAcknowledgements } from "../entities/operations/ackApi";
import { getOperationsDecision } from "../entities/operations/decisionApi";
import { getOperationsObservation } from "../entities/operations/api";
import { getReadinessReport } from "../entities/readiness/api";
import { listReports } from "../entities/report/api";
import {
  getResearchTodos,
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
    factors,
    logs,
    operationsAcknowledgements,
    operationsDecision,
    operationsObservation,
    reports,
    researchTodos,
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
    readiness
  ] = await Promise.all([
    getBackupManifest(),
    listFactors(),
    listLogs(),
    listOperationsAcknowledgements(),
    getOperationsDecision(),
    getOperationsObservation(),
    listReports(),
    getResearchTodos(),
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
    getReadinessReport()
  ]);
  const strategy = strategyDetails[strategyId] ?? strategyDetailsList[0];
  const strategySeries = strategySeriesMap[strategyId] ?? [];
  return {
    strategies,
    backupManifest,
    strategy,
    factors,
    logs,
    operationsAcknowledgements,
    operationsDecision,
    operationsObservation,
    reports,
    researchTodos,
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
    readiness
  };
}
