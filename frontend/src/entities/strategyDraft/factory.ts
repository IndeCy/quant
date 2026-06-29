import type { StrategyDraftPayload } from "./model";

type SourceFactor = {
  factor_id: string;
  name?: string;
  weight?: number;
  transform?: string;
  enabled?: boolean;
};

export function createDraftFactorsFromStrategy(factors: SourceFactor[]): StrategyDraftPayload["factors"] {
  return factors.map((factor) => ({
    factor_id: factor.factor_id,
    weight: factor.weight ?? 0,
    transform: factor.transform ?? "winsorize_zscore",
    enabled: factor.enabled ?? true
  }));
}

export function createDraftFactorsFromAvailableFactors(
  availableFactors: SourceFactor[],
  strategyFactors: SourceFactor[]
): StrategyDraftPayload["factors"] {
  const sourceById = new Map(strategyFactors.map((factor) => [factor.factor_id, factor]));
  return availableFactors.map((factor) => {
    const source = sourceById.get(factor.factor_id);
    return {
      factor_id: factor.factor_id,
      weight: source?.weight ?? 0,
      transform: source?.transform ?? "winsorize_zscore",
      enabled: source?.enabled ?? false
    };
  });
}
