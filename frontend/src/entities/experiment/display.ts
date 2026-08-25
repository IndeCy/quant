import type { ExperimentSummary } from "./model";

const ARCHIVED_STATUSES = new Set(["ARCHIVED", "RETIRED"]);
const FAILED_OUTCOMES = new Set(["FAILED", "FAIL", "REJECTED"]);

export interface ExperimentGroups {
  active: ExperimentSummary[];
  archived: ExperimentSummary[];
}

export function isArchivedExperiment(experiment: ExperimentSummary): boolean {
  const lifecycle = experiment.status.toUpperCase();
  const runStatus = experiment.latest_run_status?.toUpperCase() ?? "";
  const outcome = experiment.latest_outcome?.toUpperCase() ?? "";
  return ARCHIVED_STATUSES.has(lifecycle) || FAILED_OUTCOMES.has(runStatus) || FAILED_OUTCOMES.has(outcome);
}

export function groupExperiments(experiments: ExperimentSummary[]): ExperimentGroups {
  return experiments.reduce<ExperimentGroups>(
    (groups, experiment) => {
      groups[isArchivedExperiment(experiment) ? "archived" : "active"].push(experiment);
      return groups;
    },
    { active: [], archived: [] }
  );
}
