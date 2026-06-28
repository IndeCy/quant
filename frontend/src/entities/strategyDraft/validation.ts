import type { StrategyDraftPayload } from "./model";

type DraftFactorInput = StrategyDraftPayload["factors"][number];

export function validateStrategyDraftWeights(factors: DraftFactorInput[]): { valid: boolean; message: string } {
  const enabledFactors = factors.filter((factor) => factor.enabled);
  if (enabledFactors.length === 0) {
    return { valid: false, message: "至少需要启用一个因子" };
  }
  const total = enabledFactors.reduce((sum, factor) => sum + factor.weight, 0);
  if (Math.abs(total - 1) > 0.0001) {
    return { valid: false, message: `启用因子权重合计需要等于 1，当前为 ${total.toFixed(3)}` };
  }
  return { valid: true, message: "权重有效" };
}
