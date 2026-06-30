import type { FactorDefinition } from "../factor/model";
import type { StrategyInstance } from "./model";

export interface EditableStrategyFactor {
  factor_id: string;
  weight: number;
  transform: string;
  enabled: boolean;
}

export function createEditableFactors(factors: FactorDefinition[]): EditableStrategyFactor[] {
  return factors.map((factor, index) => ({
    factor_id: factor.factor_id,
    weight: index === 0 ? 1 : 0,
    transform: "winsorize_zscore",
    enabled: index === 0
  }));
}

export function validateEditableFactors(factors: EditableStrategyFactor[]): { valid: boolean; message: string } {
  const enabled = factors.filter((factor) => factor.enabled);
  if (enabled.length === 0) {
    return { valid: false, message: "至少需要启用一个因子" };
  }
  const total = enabled.reduce((sum, factor) => sum + factor.weight, 0);
  if (Math.abs(total - 1) > 0.0001) {
    return { valid: false, message: `启用因子权重合计需要等于 1，当前为 ${total.toFixed(3)}` };
  }
  return { valid: true, message: "权重有效" };
}

export function buildFactorTopNInstance(input: {
  strategyId: string;
  name: string;
  status: string;
  enabled: boolean;
  factors: EditableStrategyFactor[];
  topN: number;
  benchmark: string;
  riskOverlay: string;
}): StrategyInstance {
  return {
    strategy_id: input.strategyId,
    name: input.name,
    template_id: "factor_topn_monthly",
    status: input.status,
    enabled: input.enabled,
    universe: "all_a",
    filters: ["listed_3y", "exclude_st"],
    factors: input.factors
      .filter((factor) => factor.enabled)
      .map((factor) => ({
        factor_id: factor.factor_id,
        weight: factor.weight,
        transform: factor.transform
      })),
    construction: { top_n: input.topN, weighting: "equal_weight", rebalance: "monthly" },
    risk_overlay: input.riskOverlay,
    benchmark: input.benchmark
  };
}
