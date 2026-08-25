import { describe, expect, it } from "vitest";

import { environmentAuditTitle, environmentAuditTone } from "./status";

describe("environment audit status helpers", () => {
  it("maps audit status to dashboard labels", () => {
    expect(environmentAuditTitle("PASS")).toBe("环境一致");
    expect(environmentAuditTitle("FAIL")).toBe("环境漂移");
    expect(environmentAuditTone("PASS")).toBe("success");
    expect(environmentAuditTone("FAIL")).toBe("danger");
  });
});
