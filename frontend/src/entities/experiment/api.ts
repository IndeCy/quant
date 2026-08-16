import { getJson } from "../../shared/api/client";
import type { ExperimentDetail, ExperimentSummary } from "./model";

export function listExperiments(): Promise<ExperimentSummary[]> {
  return getJson<ExperimentSummary[]>("/api/research/experiments");
}

export function getExperiment(experimentId: string): Promise<ExperimentDetail> {
  return getJson<ExperimentDetail>(`/api/research/experiments/${encodeURIComponent(experimentId)}`);
}
