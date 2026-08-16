import { describe, expect, it } from "vitest";

import type { ExperimentSummary } from "./model";
import { groupExperiments, isArchivedExperiment } from "./display";

function experiment(overrides: Partial<ExperimentSummary>): ExperimentSummary {
  return {
    experiment_id: "experiment_v1",
    name: "实验 V1",
    category: "research",
    status: "active",
    owner: "",
    description: "",
    hypothesis: "",
    definition_fingerprint: "fingerprint",
    config: {},
    latest_metrics: {},
    ...overrides
  };
}

describe("experiment archive grouping", () => {
  it("archives rejected, failed and retired experiments", () => {
    expect(isArchivedExperiment(experiment({ latest_outcome: "REJECTED" }))).toBe(true);
    expect(isArchivedExperiment(experiment({ latest_run_status: "FAILED" }))).toBe(true);
    expect(isArchivedExperiment(experiment({ status: "retired" }))).toBe(true);
  });

  it("keeps passed and inconclusive research visible", () => {
    expect(isArchivedExperiment(experiment({ latest_outcome: "PASSED_RESEARCH_GATE" }))).toBe(false);
    expect(isArchivedExperiment(experiment({ latest_outcome: "INCONCLUSIVE" }))).toBe(false);
  });

  it("partitions the research list without dropping records", () => {
    const groups = groupExperiments([
      experiment({ experiment_id: "passed", latest_outcome: "PASSED" }),
      experiment({ experiment_id: "rejected", latest_outcome: "REJECTED" })
    ]);

    expect(groups.active.map((item) => item.experiment_id)).toEqual(["passed"]);
    expect(groups.archived.map((item) => item.experiment_id)).toEqual(["rejected"]);
  });
});
