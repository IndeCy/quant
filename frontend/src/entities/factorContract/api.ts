import { getJson } from "../../shared/api/client";
import type { FactorContract } from "./model";

export function listFactorContracts(): Promise<FactorContract[]> {
  return getJson<FactorContract[]>("/api/factor-contracts");
}

export function getFactorContract(factorId: string): Promise<FactorContract> {
  return getJson<FactorContract>(`/api/factor-contracts/${factorId}`);
}
