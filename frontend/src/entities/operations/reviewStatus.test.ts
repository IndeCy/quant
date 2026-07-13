import { describe, expect, it } from "vitest";

import { reviewStatusTitle, reviewStatusTone } from "./reviewStatus";

describe("operations review status helpers", () => {
  it("maps closure status to dashboard labels", () => {
    expect(reviewStatusTitle("CLOSED")).toBe("闭环完成");
    expect(reviewStatusTitle("OPEN")).toBe("仍需跟进");
    expect(reviewStatusTone("CLOSED")).toBe("success");
    expect(reviewStatusTone("OPEN")).toBe("warning");
  });
});
