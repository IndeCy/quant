import { getJson } from "../../shared/api/client";
import type { FactorDefinition } from "./model";

export function listFactors(): Promise<FactorDefinition[]> {
  return getJson<FactorDefinition[]>("/api/factors");
}
