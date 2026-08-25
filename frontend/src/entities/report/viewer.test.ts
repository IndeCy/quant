import { describe, expect, it } from "vitest";

import { detectReportViewerKind } from "./viewer";

describe("detectReportViewerKind", () => {
  it("detects markdown, csv and json reports from file path", () => {
    expect(detectReportViewerKind("/runs/20260624/daily_report.md")).toBe("markdown");
    expect(detectReportViewerKind("/runs/20260624/rebalance_plan.csv")).toBe("csv");
    expect(detectReportViewerKind("/runs/20260624/strategy_metrics.json")).toBe("json");
  });

  it("falls back to plain text for unknown extension", () => {
    expect(detectReportViewerKind("/runs/20260624/run_log.txt")).toBe("text");
  });
});
