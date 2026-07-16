import { expect, test } from "vitest";

import type { StrategyInstance } from "./model";
import { defaultAccountStrategyInstance } from "./selection";

function instance(strategyId: string, status: string): StrategyInstance {
  return {
    strategy_id: strategyId,
    name: strategyId,
    template_id: "factor_topn_monthly",
    status,
    enabled: true,
    universe: "all_a_share",
    filters: [],
    factors: [],
    construction: {},
    risk_overlay: "none",
    benchmark: "510300"
  };
}

test("defaultAccountStrategyInstance skips observation-only strategies", () => {
  const selected = defaultAccountStrategyInstance([
    instance("innovation_observer", "research_observation"),
    instance("mainline_chain_factor_v1", "shadow_live"),
    instance("quality_overlay", "active")
  ]);

  expect(selected?.strategy_id).toBe("mainline_chain_factor_v1");
});

test("defaultAccountStrategyInstance keeps a fallback when no account strategy exists", () => {
  const selected = defaultAccountStrategyInstance([instance("research_only", "research_observation")]);

  expect(selected?.strategy_id).toBe("research_only");
  expect(defaultAccountStrategyInstance([])).toBeNull();
});
