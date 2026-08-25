import { describe, expect, it } from "vitest";

import { runArtifactTypeLabel } from "./artifact";

describe("runArtifactTypeLabel", () => {
  it("maps fixed daily pipeline artifact types to readable labels", () => {
    expect(runArtifactTypeLabel("daily_report")).toBe("日报");
    expect(runArtifactTypeLabel("rebalance_plan")).toBe("调仓建议");
    expect(runArtifactTypeLabel("portfolio_snapshot")).toBe("组合快照");
    expect(runArtifactTypeLabel("strategy_metrics")).toBe("指标JSON");
    expect(runArtifactTypeLabel("unknown")).toBe("unknown");
  });
});
