import { expect, test } from "vitest";

import { catalogTone, formatBytes, qualityGateSummary } from "./status";

test("catalogTone maps source status to visual tone", () => {
  expect(catalogTone("OK")).toBe("success");
  expect(catalogTone("ERROR")).toBe("danger");
  expect(catalogTone("UNKNOWN")).toBe("neutral");
});

test("formatBytes renders compact file sizes", () => {
  expect(formatBytes(512)).toBe("512 B");
  expect(formatBytes(2048)).toBe("2.0 KB");
  expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
});

test("qualityGateSummary highlights failures", () => {
  expect(qualityGateSummary({ status: "PASS", check_count: 5, failed_count: 0, checks: [] }).tone).toBe("success");
  expect(qualityGateSummary({ status: "FAIL", check_count: 5, failed_count: 2, checks: [] }).label).toBe("2/5 failed");
});
