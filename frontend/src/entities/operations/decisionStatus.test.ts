import { describe, expect, it } from "vitest";

import { decisionTitle, decisionTone } from "./decisionStatus";

describe("operations decision status helpers", () => {
  it("maps decision state to Chinese dashboard labels", () => {
    expect(decisionTitle("NO_ACTION")).toBe("今日无需人工处理");
    expect(decisionTitle("ACTION_REQUIRED")).toBe("需要人工处理");
    expect(decisionTone("CRITICAL")).toBe("danger");
    expect(decisionTone("WARNING")).toBe("warning");
    expect(decisionTone("NORMAL")).toBe("success");
  });
});
