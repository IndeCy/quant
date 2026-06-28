import type { FactorDefinition } from "./model";

export function factorUsageLabel(factor: FactorDefinition): string {
  const enabledCount = (factor.strategies ?? []).filter((strategy) => strategy.enabled).length;
  if (enabledCount === 0) {
    return "未被策略使用";
  }
  return `${enabledCount} 个启用策略`;
}

export function factorWeightSum(factor: FactorDefinition): number {
  return (factor.strategies ?? [])
    .filter((strategy) => strategy.enabled)
    .reduce((total, strategy) => total + strategy.weight, 0);
}
