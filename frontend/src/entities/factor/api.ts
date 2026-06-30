import { getJson, postJson } from "../../shared/api/client";
import type { FactorDefinition } from "./model";

export function listFactors(): Promise<FactorDefinition[]> {
  return getJson<FactorDefinition[]>("/api/factors");
}

export function getFactor(factorId: string): Promise<FactorDefinition> {
  return getJson<FactorDefinition>(`/api/factors/${factorId}`);
}

export function saveFactor(payload: FactorDefinition): Promise<FactorDefinition> {
  return postJson<FactorDefinition>("/api/factors", payload);
}
