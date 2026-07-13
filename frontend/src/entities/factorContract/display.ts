import type { FactorContract } from "./model";

export function contractStatusLabel(contract?: FactorContract | null): string {
  return contract ? "有契约" : "无契约";
}

export function asOfLabel(contract?: Pick<FactorContract, "as_of_policy" | "as_of_field"> | null): string {
  if (!contract) {
    return "-";
  }
  return `${contract.as_of_policy || "-"} / ${contract.as_of_field || "-"}`;
}
